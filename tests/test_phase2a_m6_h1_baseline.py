import json
from pathlib import Path

import pytest

from kvopt.profiling.h1_baseline import build_h1_baseline_report
from kvopt.profiling.ingestion import ArtifactValidationError
from kvopt.workload.phase2_h1_baseline import materialize_h1_baseline_campaign

BASE_CONFIG = Path(__file__).parents[1] / "configs" / "phase2" / "metal-observability-config.json"


def test_materializes_five_identical_nonformal_baselines(tmp_path: Path) -> None:
    path = materialize_h1_baseline_campaign(BASE_CONFIG, tmp_path / "campaign")
    campaign = json.loads(path.read_text(encoding="utf-8"))
    assert campaign["identical_baseline_repeats"] == 5
    assert campaign["formal_h1_outcome_execution_authorized"] is False
    assert len(campaign["points"][0]["runs"]) == 5
    assert campaign["expected_apc_outcome"] == "FULL_HIT"


def test_report_rejects_missing_runs(tmp_path: Path) -> None:
    path = materialize_h1_baseline_campaign(BASE_CONFIG, tmp_path / "campaign")
    with pytest.raises(ArtifactValidationError, match="run directory does not exist"):
        build_h1_baseline_report(path, tmp_path / "runs")
