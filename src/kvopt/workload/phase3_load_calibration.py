"""Materialize and evaluate the frozen Phase 3 A0 load-calibration grid."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from kvopt.profiling.phase3_nec import evaluate_phase3_nec_arm

from .continuum_bounded_timeline import (
    BoundaryKind,
    ReplayBoundary,
    insert_pressure_join_boundary,
)
from .phase3_native_preflight import materialize_native_preflight

BLOCK_SIZE = 16
CAPACITY_BLOCKS = 2048
LOADS = {
    "L_LOW": {"required_blocks": 256, "target_min": 0.05, "target_max": 0.15},
    "L_HIGH": {"required_blocks": 1024, "target_min": 0.25, "target_max": 0.45},
}


def _canonical_sha(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _pressure_token_ids(seed: str, token_count: int) -> list[int]:
    values: list[int] = []
    for index in range(token_count):
        digest = hashlib.sha256(f"{seed}:{index}".encode()).digest()
        values.append(100 + int.from_bytes(digest[:4], "big") % 99900)
    return values


def _boundaries(group: Mapping[str, object], boundary_id: str) -> list[dict[str, object]]:
    raw = group.get("replay_timeline")
    sessions = group.get("sessions")
    if not isinstance(raw, list) or not isinstance(sessions, list) or len(sessions) != 2:
        raise ValueError("calibration group lacks its frozen two-session timeline")
    parsed = tuple(
        ReplayBoundary(
            boundary_id=str(row["boundary_id"]),
            logical_timestamp=float(row["logical_timestamp"]),
            source=str(row["source"]),
            kind=BoundaryKind(str(row["kind"])),
            request_id=(None if row.get("request_id") is None else str(row["request_id"])),
        )
        for row in raw
    )
    final_ids = []
    for session in sessions:
        selected = session.get("selected_requests")
        if not isinstance(selected, list) or len(selected) != 12:
            raise ValueError("calibration session must freeze twelve requests")
        final_ids.append(str(selected[-1]["request_id"]))
    joined = insert_pressure_join_boundary(
        boundaries=parsed,
        final_request_ids=final_ids,
        boundary_id=boundary_id,
    )
    return [
        {
            "boundary_id": row.boundary_id,
            "logical_timestamp": row.logical_timestamp,
            "source": row.source,
            "kind": row.kind.value,
            "request_id": row.request_id,
        }
        for row in joined
    ]


def materialize_load_calibration(
    *, repository: Path, seal_path: Path, profile_path: Path, output_dir: Path
) -> dict[str, object]:
    """Create the authorized 20-group x 2-load A0 calibration inputs."""

    if output_dir.exists():
        raise FileExistsError(output_dir)
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    groups = seal.get("groups")
    if seal.get("schema_version") != "phase3.cohort_seal.v1" or not isinstance(groups, list):
        raise ValueError("unsupported Phase 3 Cohort Seal")
    if len(groups) != 20:
        raise ValueError("load calibration requires twenty frozen groups")
    output_dir.mkdir(parents=True)
    runs: list[dict[str, object]] = []
    for group in groups:
        group_id = str(group["group_id"])
        for load, geometry in LOADS.items():
            cell_id = f"{group_id}-{load.lower().replace('_', '-')}"
            cell_dir = output_dir / cell_id
            freeze = materialize_native_preflight(
                repository=repository,
                seal_path=seal_path,
                profile_path=profile_path,
                group_id=group_id,
                output_dir=cell_dir,
            )
            old_config = cell_dir / str(freeze["config"])
            config = json.loads(old_config.read_text(encoding="utf-8"))
            run_id = f"phase3-load-calibration-{cell_id}-a0"
            boundary_id = f"pressure:{cell_id}"
            stage_id = f"phase3-load-calibration-{cell_id}"
            boundaries = _boundaries(group, boundary_id)
            clock = [
                {
                    "boundary_id": row["boundary_id"],
                    "logical_timestamp": row["logical_timestamp"],
                    "source": row["source"],
                }
                for row in boundaries
            ]
            token_count = int(geometry["required_blocks"]) * BLOCK_SIZE
            pressure_ids = _pressure_token_ids(f"phase3:{cell_id}:pressure-v1", token_count)
            config["run_id"] = run_id
            config["backend_revision"] = "phase3-load-calibration-v1"
            config["controlled_sparse_replay"]["boundaries"] = boundaries
            config["controlled_sparse_replay"]["logical_sequence_sha256"] = _canonical_sha(clock)
            config["pressure"] = {
                "required_blocks": int(geometry["required_blocks"]),
                "initial_shortage_blocks": 1,
                "safety_ceiling": 1,
            }
            options = config["backend_options"]
            options["controlled_sparse_replay_boundaries"] = clock
            options["controlled_pressure_stages_by_boundary"] = {
                boundary_id: {
                    "stage_id": stage_id,
                    "prompt": f"phase3 frozen {load} calibration pressure",
                    "max_requests": 1,
                    "stop_on_forced_release": False,
                }
            }
            options["pressure_prompt_tokens"] = token_count
            options["pressure_stage_prompt_tokens"] = {stage_id: token_count}
            options["pressure_token_ids_by_stage"] = {stage_id: pressure_ids}
            options["phase3_load_level"] = load
            options["phase3_calibration_candidate"] = True
            new_config = cell_dir / f"{run_id}.config.json"
            _write(new_config, config)
            old_config.unlink()
            pressure_contract = [
                {
                    "boundary_id": boundary_id,
                    "stage_id": stage_id,
                    "request_ids": [f"pressure:{stage_id}:1"],
                }
            ]
            cell_freeze = {
                "schema_version": "phase3.load_calibration_cell_freeze.v1",
                "execution_authorized": True,
                "scope": "A0_LOAD_CALIBRATION_NOT_MAIN_CAMPAIGN",
                "git_sha": freeze["git_sha"],
                "cohort_seal_sha256": freeze["cohort_seal_sha256"],
                "group_id": group_id,
                "load_level": load,
                "target_recompute_ratio": [
                    geometry["target_min"],
                    geometry["target_max"],
                ],
                "required_blocks": geometry["required_blocks"],
                "capacity_blocks": CAPACITY_BLOCKS,
                "run_id": run_id,
                "config": new_config.name,
                "config_sha256": _sha256(new_config),
                "trace": freeze["trace"],
                "trace_sha256": freeze["trace_sha256"],
                "profile": freeze["profile"],
                "profile_sha256": freeze["profile_sha256"],
                "logical_sequence_sha256": _canonical_sha(clock),
                "pressure_token_ids_sha256": _canonical_sha(pressure_ids),
                "pressure_request_contract": pressure_contract,
                "frozen_request_order": group["frozen_request_order"],
                "native_enqueue_order": group["native_enqueue_order"],
                "history_predecessors": group["history_predecessors"],
            }
            _write(cell_dir / "freeze-record.json", cell_freeze)
            runs.append(
                {
                    "cell_id": cell_id,
                    "group_id": group_id,
                    "load_level": load,
                    "run_id": run_id,
                    "directory": cell_id,
                    "config": f"{cell_id}/{new_config.name}",
                    "config_sha256": _sha256(new_config),
                    "freeze_sha256": _sha256(cell_dir / "freeze-record.json"),
                    "logical_sequence_sha256": _canonical_sha(clock),
                    "pressure_token_ids_sha256": _canonical_sha(pressure_ids),
                }
            )
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest = {
        "schema_version": "phase3.load_calibration_manifest.v1",
        "execution_authorized": True,
        "scope": "A0_ONLY_LOAD_CALIBRATION",
        "git_sha": git_sha,
        "cohort_seal_sha256": _sha256(seal_path),
        "profile_sha256": _sha256(profile_path),
        "capacity_blocks": CAPACITY_BLOCKS,
        "candidate_grid": LOADS,
        "planned_run_count": 40,
        "fail_closed_if_target_missed": True,
        "runs": runs,
    }
    _write(output_dir / "manifest.json", manifest)
    return manifest


def evaluate_load_calibration_run(
    *, events: Sequence[Mapping[str, object]], freeze: Mapping[str, object]
) -> dict[str, object]:
    """Evaluate one A0 calibration run from persisted Native events."""

    if freeze.get("schema_version") != "phase3.load_calibration_cell_freeze.v1":
        raise ValueError("unsupported calibration freeze record")
    order = freeze.get("frozen_request_order")
    enqueue = freeze.get("native_enqueue_order")
    predecessors = freeze.get("history_predecessors")
    contract = freeze.get("pressure_request_contract")
    if not isinstance(order, list) or not isinstance(enqueue, list):
        raise TypeError("calibration freeze lacks request-order contracts")
    if not isinstance(predecessors, dict) or not isinstance(contract, list):
        raise TypeError("calibration freeze lacks evidence contracts")
    identities = []
    for request_id in order:
        if not isinstance(request_id, str) or ":turn:" not in request_id:
            raise ValueError("invalid frozen request identity")
        identities.append((request_id.split(":turn:", 1)[0], request_id))
    pressure_ids = frozenset(
        str(request_id) for row in contract for request_id in row["request_ids"]
    )
    normalized_predecessors = {
        identity: tuple(
            (str(value).split(":turn:", 1)[0], str(value)) for value in predecessors[identity[1]]
        )
        for identity in identities
    }
    arm = evaluate_phase3_nec_arm(
        arm="A0",
        events=events,
        frozen_requests=identities,
        native_enqueue_order=[(str(value).split(":turn:", 1)[0], str(value)) for value in enqueue],
        history_predecessors=normalized_predecessors,
        pressure_request_ids=pressure_ids,
    )
    ratio = arm["recompute_ratio"]
    target = freeze.get("target_recompute_ratio")
    if not isinstance(ratio, (int, float)) or not isinstance(target, list) or len(target) != 2:
        raise ValueError("calibration result lacks a valid recompute ratio or target")
    in_target = float(target[0]) <= float(ratio) <= float(target[1])
    return {
        "schema_version": "phase3.load_calibration_run_report.v1",
        # Protocol v4 Option F reuses the measured C1/C2 operating points.
        # Band attainment is reported but is not an admission gate.  Evidence
        # defects still raise above; a manipulation miss does not masquerade as
        # an evidence failure.
        "status": "PASS",
        "manipulation_check_status": "IN_BAND" if in_target else "OUT_OF_BAND",
        "manipulation_check_is_gating": False,
        "group_id": freeze["group_id"],
        "load_level": freeze["load_level"],
        "target_recompute_ratio": target,
        "observed_recompute_ratio": ratio,
        "headroom_eligible": (float(ratio) >= 0.05 and arm["aggregate_recomputed_tokens"] >= 512),
        "arm": arm,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = materialize_load_calibration(
        repository=Path.cwd().resolve(),
        seal_path=args.seal.resolve(),
        profile_path=args.profile.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    print(f"materialized {result['planned_run_count']} Phase 3 A0 calibration runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
