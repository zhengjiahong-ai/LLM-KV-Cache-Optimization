"""Build the fail-closed ledger for adjudicated Phase 5 SWE acquisition failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from .phase5_replay import canonical_sha256

LEDGER_SCHEMA = "phase5.swe_acquisition_failure_ledger.v1"
FAILURE_CODE = "INFRASTRUCTURE_INCOMPLETE_CHUNKED_READ"
FAILURE_CLASS = "INFRASTRUCTURE_RESPONSE_INTERRUPTION"
FAILURE_MARKER = "incomplete chunked read"


def _load(path: Path, label: str) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _failure_entry(row: Mapping[str, object]) -> dict[str, object]:
    instance_id = str(row.get("instance_id", ""))
    run_directory = Path(str(row.get("run_directory", "")))
    run_path = run_directory / "run.json"
    if not instance_id or not run_path.is_file():
        raise FileNotFoundError("unresolved acquisition lacks its immutable run.json")
    run = _load(run_path, "run.json")
    reason = str(run.get("failure_reason", ""))
    if (
        run.get("status") != "failed"
        or run.get("agent_outcome") != "FAILED"
        or run.get("agent_exit_status") != "RemoteProtocolError"
        or FAILURE_MARKER not in reason
    ):
        raise ValueError("unresolved acquisition does not match the M4 failure class")
    if run.get("instance_id") != instance_id:
        raise ValueError("failure run identity differs from reconciliation identity")
    artifacts: dict[str, str] = {"run.json": _sha256(run_path)}
    sidecar_path = run_directory / "acquisition-sidecar.json"
    if sidecar_path.is_file():
        artifacts[sidecar_path.name] = _sha256(sidecar_path)
    trajectories = sorted(run_directory.glob("*.traj.json"))
    if len(trajectories) > 1:
        raise ValueError("failed acquisition contains multiple trajectory files")
    if trajectories:
        artifacts[trajectories[0].name] = _sha256(trajectories[0])
    return {
        "instance_id": instance_id,
        "terminal_state": "FAILED",
        "resolution_status": "UNRESOLVED",
        "failure_code": FAILURE_CODE,
        "failure_class": FAILURE_CLASS,
        "failure_reason": reason,
        "right_censored": False,
        "qualification_status": "EXCLUDED",
        "retry_status": "NO_FURTHER_RETRY_WITHOUT_NEW_M1_AUTHORIZATION",
        "completed_session": False,
        "attempt_source": row.get("attempt_source"),
        "run_directory": str(run_directory.resolve()),
        "model_call_count": run.get("model_call_count"),
        "tool_call_count": run.get("tool_call_count"),
        "artifact_sha256": artifacts,
        "artifact_set_sha256": canonical_sha256(artifacts),
    }


def build_failure_ledger(reconciliation_path: Path) -> dict[str, object]:
    """Bind every unresolved identity to one adjudicated response interruption."""

    reconciliation = _load(reconciliation_path, "reconciliation")
    if reconciliation.get("status") != "COMPLETE":
        raise ValueError("acquisition reconciliation is not complete")
    unresolved = reconciliation.get("unresolved_candidate_ids")
    attempts = reconciliation.get("attempts")
    if not isinstance(unresolved, list) or not isinstance(attempts, list):
        raise TypeError("reconciliation lacks unresolved identities or attempts")
    if len(unresolved) != len(set(unresolved)):
        raise ValueError("reconciliation contains duplicate unresolved identities")
    entries: list[dict[str, object]] = []
    for identity in unresolved:
        matches = [
            row
            for row in attempts
            if isinstance(row, Mapping)
            and row.get("instance_id") == identity
            and row.get("status") == "failed"
            and FAILURE_MARKER in str(row.get("failure_reason", ""))
        ]
        if len(matches) != 1:
            raise ValueError(
                f"unresolved identity must have one adjudicated failure: {identity}"
            )
        entries.append(_failure_entry(matches[0]))
    payload: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA,
        "status": "COMPLETE",
        "adjudication": "M4_PHASE5_SWE_2026_11_21",
        "reconciliation_path": str(reconciliation_path.resolve()),
        "reconciliation_sha256": _sha256(reconciliation_path),
        "failed_session_count": len(entries),
        "entries": entries,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    return {**payload, "ledger_sha256": canonical_sha256(payload)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_failure_ledger(arguments.reconciliation.resolve())
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote: {arguments.output.resolve()}")
    print(f"sha256: {_sha256(arguments.output)}")
    print("PHASE5_SWE_FAILURE_LEDGER: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
