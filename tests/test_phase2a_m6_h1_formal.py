import json
from pathlib import Path

import pytest

from kvopt.workload.phase2_formal_runner import load_formal_campaign
from kvopt.workload.phase2_h1_formal import materialize_h1_formal_campaign
from kvopt.workload.phase2_h1_materialize import materialize_h1_scenarios

ROOT = Path(__file__).parents[1]
DESIGN = ROOT / "configs/phase2/h1-independent-campaign-design-v2.json"
FREEZE = ROOT / "configs/phase2/h1-scenario-materialization-freeze-v2.json"
AUTHORIZATION = ROOT / "docs/experiments/phase2a-m6-h1/formal-level-a-execution-authorization.json"
BASE_CONFIG = ROOT / "configs/phase2/metal-observability-config.json"
COMMIT = "1" * 40


def _sealed(tmp_path: Path) -> tuple[Path, Path]:
    seal = materialize_h1_scenarios(DESIGN, FREEZE, tmp_path / "sealed")
    return seal.parent / "scenario-manifest.json", seal


def test_materializes_exact_authorized_level_a_campaign(tmp_path: Path) -> None:
    manifest, seal = _sealed(tmp_path)
    campaign = materialize_h1_formal_campaign(
        scenario_manifest_path=manifest,
        scenario_seal_path=seal,
        authorization_path=AUTHORIZATION,
        base_config_path=BASE_CONFIG,
        output=tmp_path / "campaign",
        execution_code_commit=COMMIT,
    )
    payload = json.loads(campaign.read_text())
    loaded = load_formal_campaign(campaign)

    assert payload["planned_run_count"] == 126
    assert payload["family_scenario_counts"] == {
        family: 7 for family in ("F1", "F2", "F3", "F4", "F5", "F6")
    }
    assert payload["formal_h1_outcome_execution_authorized"] is True
    assert payload["challenger_runtime_policy_switch_authorized"] is False
    assert payload["primary_metric"] == "planned_return_weighted_prefill_proxy"
    assert loaded.required_execution_commit == COMMIT
    assert len(loaded.scenarios) == 42


def test_refuses_authorization_with_runtime_policy_switch(tmp_path: Path) -> None:
    manifest, seal = _sealed(tmp_path)
    authorization = json.loads(AUTHORIZATION.read_text())
    authorization["challenger"]["runtime_policy_switch_authorized"] = True
    invalid = tmp_path / "authorization.json"
    invalid.write_text(json.dumps(authorization))

    with pytest.raises(ValueError, match="policy switch"):
        materialize_h1_formal_campaign(
            scenario_manifest_path=manifest,
            scenario_seal_path=seal,
            authorization_path=invalid,
            base_config_path=BASE_CONFIG,
            output=tmp_path / "campaign",
            execution_code_commit=COMMIT,
        )
