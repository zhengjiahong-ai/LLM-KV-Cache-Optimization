import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.phase2g_a1_bounded_authorize import build_authorization


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    gate1 = tmp_path / "gate1.json"
    manifest = tmp_path / "manifest.json"
    validation = tmp_path / "validation.json"
    gate1.write_text(
        json.dumps(
            {
                "schema_version": "phase2g.a1_native_gate1_report.v1",
                "gate": "FAIL",
                "gate2_ready": False,
            }
        ),
        encoding="utf-8",
    )
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "phase2g.a1_bounded_materialization.v1",
                "execution_authorized": False,
                "scenario_count": 36,
                "planned_run_count": 144,
                "runs": [],
            }
        ),
        encoding="utf-8",
    )
    validation.write_text(
        json.dumps(
            {
                "status": "PASS",
                "manifest_sha256": _sha(manifest),
                "family_counts": {},
            }
        ),
        encoding="utf-8",
    )
    return gate1, manifest, validation


def test_authorization_rejects_failed_gate1(tmp_path: Path) -> None:
    gate1, manifest, validation = _files(tmp_path)

    with pytest.raises(ValueError, match="Gate 1 must pass"):
        build_authorization(
            repository=Path(__file__).parents[1],
            gate1_report=gate1,
            campaign_manifest=manifest,
            validation_report=validation,
        )


def test_authorization_rejects_validation_manifest_drift(tmp_path: Path) -> None:
    gate1, manifest, validation = _files(tmp_path)
    gate1.write_text(
        json.dumps(
            {
                "schema_version": "phase2g.a1_native_gate1_report.v1",
                "gate": "PASS",
                "gate2_ready": True,
            }
        ),
        encoding="utf-8",
    )
    validation.write_text(
        json.dumps({"status": "PASS", "manifest_sha256": "wrong", "family_counts": {}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not bound"):
        build_authorization(
            repository=Path(__file__).parents[1],
            gate1_report=gate1,
            campaign_manifest=manifest,
            validation_report=validation,
        )
