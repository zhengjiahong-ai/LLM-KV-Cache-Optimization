import json
from pathlib import Path

import pytest

from kvopt.workload.phase2e_freeze import build_freeze_candidate


def test_freeze_candidate_rejects_unvalidated_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    validation = tmp_path / "validation.json"
    manifest.write_text(json.dumps({"scenario_count": 36, "runs": []}), encoding="utf-8")
    validation.write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")

    with pytest.raises(ValueError, match="validation must pass"):
        build_freeze_candidate(
            repository=Path(__file__).parents[1],
            campaign_manifest=manifest,
            validation_report=validation,
        )
