"""Freeze and validate the bounded W1-B three-arm Native smoke protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_protocol(
    *,
    protocol_path: Path,
    output_path: Path,
    native_fidelity_report_path: Path | None = None,
) -> dict[str, Any]:
    protocol = _load(protocol_path)
    if protocol.get("schema_version") != "continuum.w1b_native_smoke_protocol.v1":
        raise ValueError("unsupported W1-B smoke protocol")
    if protocol.get("formal_performance_campaign_authorized") is not False:
        raise ValueError("W1-B is not a formal performance campaign")
    if protocol.get("arms") != ["A0", "A1", "A2"]:
        raise ValueError("W1-B must freeze exactly the A0/A1/A2 arms")
    if protocol.get("runtime_repeats") != 1:
        raise ValueError("W1-B bounded smoke permits one run per arm and group")
    schedule = protocol.get("schedule")
    if not isinstance(schedule, dict) or schedule.get("kind") != ("CONTROLLED_REPLAY_SCHEDULE"):
        raise ValueError("W1-B cross-session schedule must be explicitly controlled")
    if schedule.get("mode") != "CAUSAL_REPLAY":
        raise ValueError("W1-B v1 freezes causal replay rather than open-loop timing")
    source_path = Path(str(protocol.get("source_replay_manifest")))
    source = _load(source_path)
    if source.get("schema_version") != "continuum.w1b_native_replay_manifest.v1":
        raise ValueError("W1-B smoke source is not a frozen replay manifest")
    if source.get("native_comparability_smoke_executed") is not False:
        raise ValueError("W1-B source replay has already been used for a smoke")
    root = source_path.parent
    source_bindings = {row["session_id"]: row for row in source["sessions"]}
    groups = protocol.get("groups")
    if not isinstance(groups, list) or not 3 <= len(groups) <= 5:
        raise ValueError("W1-B smoke requires three to five preselected groups")
    group_ids: set[str] = set()
    selected_sessions: set[str] = set()
    frozen_groups: list[dict[str, Any]] = []
    max_model_len = int(protocol["runtime"]["max_model_len"])
    for group in groups:
        group_id = group.get("group_id")
        if not isinstance(group_id, str) or group_id in group_ids:
            raise ValueError("W1-B group IDs must be unique strings")
        group_ids.add(group_id)
        selections = group.get("sessions")
        if not isinstance(selections, list) or len(selections) < 2:
            raise ValueError("each W1-B group must contain at least two sessions")
        frozen_sessions: list[dict[str, Any]] = []
        for selection in selections:
            session_id = selection.get("session_id")
            if session_id not in source_bindings:
                raise ValueError("W1-B group references an unknown source session")
            if session_id in selected_sessions:
                raise ValueError("a W1-B session may belong to only one smoke group")
            selected_sessions.add(session_id)
            binding = source_bindings[session_id]
            session_path = root / binding["path"]
            if _sha256(session_path) != binding["sha256"]:
                raise ValueError("W1-B source session SHA-256 mismatch")
            session = _load(session_path)
            turns = selection.get("turns")
            if (
                not isinstance(turns, list)
                or not turns
                or turns != sorted(set(turns))
                or any(not isinstance(turn, int) or turn < 1 for turn in turns)
            ):
                raise ValueError("W1-B selected turns must be unique increasing integers")
            requests = session["requests"]
            if turns[-1] > len(requests):
                raise ValueError("W1-B selected turn is outside the source session")
            selected = [requests[turn - 1] for turn in turns]
            if any(row["token_count"] + 1 > max_model_len for row in selected):
                raise ValueError("W1-B selected request exceeds frozen model context")
            frozen_sessions.append(
                {
                    "session_id": session_id,
                    "source_session_sha256": binding["sha256"],
                    "completion_status": session["completion_status"],
                    "right_censored": session["right_censored"],
                    "selected_turns": turns,
                    "selected_request_ids": [row["request_id"] for row in selected],
                    "selected_token_counts": [row["token_count"] for row in selected],
                    "selected_token_sha256": [row["token_ids_sha256"] for row in selected],
                }
            )
        frozen_groups.append(
            {
                "group_id": group_id,
                "selection_basis": group.get("selection_basis"),
                "sessions": frozen_sessions,
            }
        )
    run_plan = [
        {
            "run_id": f"{group_id}-{arm.lower()}-repeat-1",
            "group_id": group_id,
            "arm": arm,
            "repeat": 1,
        }
        for group_id in sorted(group_ids)
        for arm in protocol["arms"]
    ]
    native_fidelity_status = "PENDING"
    native_fidelity_binding = None
    if native_fidelity_report_path is not None:
        fidelity = _load(native_fidelity_report_path)
        native_fidelity_status = fidelity.get("verdict")
        if native_fidelity_status != "PASS_NATIVE_INPUT_FIDELITY_ONLY":
            raise ValueError("W1-B Native fidelity report has not passed")
        native_fidelity_binding = {
            "path": str(native_fidelity_report_path),
            "sha256": _sha256(native_fidelity_report_path),
        }
    freeze = {
        "schema_version": "continuum.w1b_native_smoke_freeze.v1",
        "scope": protocol["scope"],
        "protocol_path": str(protocol_path),
        "protocol_sha256": _sha256(protocol_path),
        "source_replay_manifest": str(source_path),
        "source_replay_manifest_sha256": _sha256(source_path),
        "selection_uses_policy_outcomes": False,
        "groups": frozen_groups,
        "group_count": len(frozen_groups),
        "arms": protocol["arms"],
        "planned_run_count": len(run_plan),
        "run_plan": run_plan,
        "schedule": schedule,
        "runtime": protocol["runtime"],
        "gates": protocol["gates"],
        "native_fidelity_status": native_fidelity_status,
        "native_fidelity_binding": native_fidelity_binding,
        "execution_authorized_by_freeze": native_fidelity_status
        == "PASS_NATIVE_INPUT_FIDELITY_ONLY",
        "formal_performance_campaign_authorized": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return freeze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-fidelity-report", type=Path)
    args = parser.parse_args()
    freeze = freeze_protocol(
        protocol_path=args.protocol,
        output_path=args.output,
        native_fidelity_report_path=args.native_fidelity_report,
    )
    print(
        f"froze W1-B smoke: {freeze['group_count']} groups, "
        f"{freeze['planned_run_count']} planned runs -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
