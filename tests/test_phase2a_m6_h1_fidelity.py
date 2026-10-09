import json
from pathlib import Path

import pytest

from kvopt.profiling.h1_fidelity import build_fidelity_report
from kvopt.workload.phase2_h1_compiler import materialize_fidelity_campaign
from kvopt.workload.phase2_h1_fidelity_runner import execute_fidelity_campaign

BASE_CONFIG = Path(__file__).parents[1] / "configs/phase2/metal-observability-config.json"


def test_runner_rejects_formal_authorization(tmp_path: Path) -> None:
    campaign = materialize_fidelity_campaign(BASE_CONFIG, tmp_path / "campaign")
    payload = json.loads(campaign.read_text())
    payload["formal_h1_outcome_execution_authorized"] = True
    campaign.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="must not authorize"):
        execute_fidelity_campaign(campaign, tmp_path / "runs")


def test_report_rejects_wrong_campaign(tmp_path: Path) -> None:
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps({"campaign_kind": "formal"}))
    with pytest.raises(ValueError, match="unsupported"):
        build_fidelity_report(path, tmp_path / "runs")
