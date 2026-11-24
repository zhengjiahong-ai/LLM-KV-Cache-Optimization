"""Execute the frozen Phase 5 SWE acquisition frame without selecting a cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from .continuum_w1a_runner import run_one
from .phase3_acquisition import run_batch
from .phase5_replay import canonical_sha256

FRAME_SCHEMA = "phase5.swe_sampling_frame.v1"
FRAME_STATUS = "FROZEN_ACQUISITION_FRAME_NOT_FORMAL_COHORT"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("SWE sampling frame must be an object")
    return value


def validate_swe_frame(frame: Mapping[str, object]) -> tuple[str, ...]:
    if frame.get("schema_version") != FRAME_SCHEMA:
        raise ValueError("unsupported Phase 5 SWE frame schema")
    if frame.get("status") != FRAME_STATUS:
        raise ValueError("Phase 5 SWE frame is not frozen for acquisition")
    payload = dict(frame)
    expected_sha = payload.pop("frame_sha256", None)
    if not isinstance(expected_sha, str) or canonical_sha256(payload) != expected_sha:
        raise ValueError("Phase 5 SWE frame SHA-256 mismatch")
    candidates = frame.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 84:
        raise ValueError("Phase 5 SWE frame must contain 84 candidates")
    if [row.get("phase5_rank") for row in candidates if isinstance(row, dict)] != list(
        range(1, 85)
    ):
        raise ValueError("Phase 5 SWE ranks must be contiguous")
    identities = [str(row.get("instance_id", "")) for row in candidates]
    if any(not identity for identity in identities) or len(set(identities)) != 84:
        raise ValueError("Phase 5 SWE identities must be non-empty and unique")
    roles = Counter(str(row.get("candidate_role")) for row in candidates)
    expected_roles = {"PRIMARY": 40, "RESERVE": 24, "HISTORICAL_REUSE_RESERVE": 20}
    if dict(roles) != expected_roles:
        raise ValueError("Phase 5 SWE role counts differ from the frozen contract")
    if frame.get("historical_policy", {}).get("may_enter_formal_cohort_without_m1") is not False:
        raise ValueError("historical W1-C candidates must remain ledger-only")
    return tuple(
        str(row["instance_id"])
        for row in candidates
        if row.get("candidate_role") == "PRIMARY"
    )


def validate_historical_authorization(
    authorization: Mapping[str, object], frame: Mapping[str, object]
) -> tuple[str, ...]:
    """Bind the M1 decision to the exact frozen ranks 65--84."""

    payload = dict(authorization)
    expected_sha = payload.pop("authorization_sha256", None)
    if not isinstance(expected_sha, str) or canonical_sha256(payload) != expected_sha:
        raise ValueError("historical reacquisition authorization SHA-256 mismatch")
    if authorization.get("schema_version") != "phase5.swe_historical_reacquisition_authorization.v1":
        raise ValueError("unsupported historical reacquisition authorization")
    if authorization.get("status") != "M1_AUTHORIZED_2026_11_24":
        raise ValueError("historical reacquisition is not M1-authorized")
    if authorization.get("execution_authorized") is not True:
        raise ValueError("historical reacquisition execution is disabled")
    candidates = frame.get("candidates")
    if not isinstance(candidates, list):
        raise TypeError("SWE frame candidates must be an array")
    frozen_rows = [
        row
        for row in candidates
        if isinstance(row, dict) and 65 <= int(row["phase5_rank"]) <= 84
    ]
    frozen_ids = tuple(str(row["instance_id"]) for row in frozen_rows)
    if [row["phase5_rank"] for row in frozen_rows] != list(range(65, 85)):
        raise ValueError("historical reacquisition ranks are not exact")
    if any(row.get("candidate_role") != "HISTORICAL_REUSE_RESERVE" for row in frozen_rows):
        raise ValueError("historical reacquisition role drifted")
    if authorization.get("ordered_instance_ids") != list(frozen_ids):
        raise ValueError("historical reacquisition identity order drifted")
    if authorization.get("sampling_frame_canonical_sha256") != frame.get("frame_sha256"):
        raise ValueError("authorization does not bind the frozen frame")
    if authorization.get("candidate_ranks") != list(range(65, 85)):
        raise ValueError("authorization does not bind exact ranks 65--84")
    if authorization.get("candidate_count") != 20:
        raise ValueError("authorization must cover all 20 historical candidates")
    if authorization.get("old_w1c_evidence_may_be_reused") is not False:
        raise ValueError("old W1-C evidence reuse must remain forbidden")
    if authorization.get("gpu_execution_authorized") is not False:
        raise ValueError("historical acquisition cannot authorize GPU execution")
    return frozen_ids


def write_historical_batch_manifest(
    *,
    frame_path: Path,
    config_path: Path,
    authorization_path: Path,
    output_root: Path,
    ordered_ids: tuple[str, ...],
) -> Path:
    output_root.mkdir(parents=True, exist_ok=False)
    manifest_path = output_root / "phase5-historical-reacquisition-batch.json"
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    manifest = {
        "schema_version": "phase5.swe_historical_reacquisition_batch.v1",
        "status": "HISTORICAL_REACQUISITION_STARTED",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "frame_path": str(frame_path.resolve()),
        "frame_file_sha256": _sha256(frame_path),
        "frozen_frame_sha256": _load(frame_path)["frame_sha256"],
        "authorization_path": str(authorization_path.resolve()),
        "authorization_file_sha256": _sha256(authorization_path),
        "runner_config_path": str(config_path.resolve()),
        "runner_config_sha256": _sha256(config_path),
        "candidate_role": "HISTORICAL_REUSE_RESERVE",
        "candidate_ranks": list(range(65, 85)),
        "candidate_count": 20,
        "ordered_instance_ids": list(ordered_ids),
        "execute_all_candidates_without_early_stop": True,
        "old_w1c_evidence_reused": False,
        "formal_cohort_selected": False,
        "gpu_calibration_authorized": False,
        "formal_campaign_authorized": False,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def write_batch_manifest(
    *, frame_path: Path, config_path: Path, output_root: Path, primary_ids: tuple[str, ...]
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "phase5-acquisition-batch.json"
    if manifest_path.exists():
        existing = _load(manifest_path)
        if existing.get("frame_file_sha256") != _sha256(frame_path):
            raise ValueError("existing batch manifest binds a different SWE frame")
        return manifest_path
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    manifest = {
        "schema_version": "phase5.swe_acquisition_batch.v1",
        "status": "PRIMARY_ACQUISITION_STARTED",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "frame_path": str(frame_path.resolve()),
        "frame_file_sha256": _sha256(frame_path),
        "frozen_frame_sha256": _load(frame_path)["frame_sha256"],
        "runner_config_path": str(config_path.resolve()),
        "runner_config_sha256": _sha256(config_path),
        "candidate_role": "PRIMARY",
        "candidate_count": 40,
        "ordered_instance_ids": list(primary_ids),
        "historical_w1c_authorized": False,
        "formal_cohort_selected": False,
        "gpu_calibration_authorized": False,
        "formal_campaign_authorized": False,
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--source-checkout", type=Path, required=True)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--runner-config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--maximum-tasks", type=int, default=40)
    parser.add_argument("--historical-authorization", type=Path)
    arguments = parser.parse_args()
    frame_path = arguments.frame.resolve()
    config_path = arguments.runner_config.resolve()
    output_root = arguments.output_root.resolve()
    frame = _load(frame_path)
    primary_ids = validate_swe_frame(frame)
    if arguments.historical_authorization is not None:
        authorization_path = arguments.historical_authorization.resolve()
        historical_ids = validate_historical_authorization(
            _load(authorization_path), frame
        )
        manifest_path = write_historical_batch_manifest(
            frame_path=frame_path,
            config_path=config_path,
            authorization_path=authorization_path,
            output_root=output_root,
            ordered_ids=historical_ids,
        )
        outputs = [
            run_one(
                repository=arguments.repository.resolve(),
                source_checkout=arguments.source_checkout.resolve(),
                config_path=config_path,
                instance_id=instance_id,
                output_root=output_root,
            )
            for instance_id in historical_ids
        ]
        print(
            json.dumps(
                {
                    "batch_manifest": str(manifest_path),
                    "attempted": len(outputs),
                    "run_directories": [str(path) for path in outputs],
                },
                indent=2,
            )
        )
        return 0
    manifest_path = write_batch_manifest(
        frame_path=frame_path,
        config_path=config_path,
        output_root=output_root,
        primary_ids=primary_ids,
    )
    outputs = run_batch(
        repository=arguments.repository.resolve(),
        source_checkout=arguments.source_checkout.resolve(),
        config_path=config_path,
        output_root=output_root,
        roles=("PRIMARY",),
        maximum_tasks=arguments.maximum_tasks,
        instance_ids=primary_ids,
    )
    print(
        json.dumps(
            {
                "batch_manifest": str(manifest_path),
                "attempted": len(outputs),
                "run_directories": [str(path) for path in outputs],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
