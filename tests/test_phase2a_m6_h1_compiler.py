import json
from pathlib import Path

from kvopt.workload.phase2 import load_phase2_trace
from kvopt.workload.phase2_h1_compiler import (
    compile_h1_scenario,
    materialize_fidelity_campaign,
    non_holdout_fixtures,
)

BASE_CONFIG = Path(__file__).parents[1] / "configs/phase2/metal-observability-config.json"


def test_compiler_maps_every_axis_without_authorizing_outcomes() -> None:
    base = json.loads(BASE_CONFIG.read_text())
    config, trace, evidence = compile_h1_scenario(non_holdout_fixtures()[1], base)

    assert config["campaign_kind"] == "h1_compiler_fidelity_validation"
    assert len(trace.pressure_stages) == 1
    assert evidence["evidence_tier"] == "LEVEL_A_PROXY_FIRST"
    assert evidence["silent_fallback_permitted"] is False
    assert evidence["formal_h1_outcome_execution_authorized"] is False
    assert evidence["challenger_runtime_policy_switch_authorized"] is False
    contracts = evidence["candidate_contracts"]
    assert contracts[0]["controlled_inputs"]["ownership_group"] == "shared-0"
    assert contracts[0]["cleanup_request_id"] is not None
    assert contracts[0]["return_request_id"] is None
    assert contracts[1]["trace_derived_proxy_inputs"]["eta"] == 1.0


def test_repeated_pressure_precedes_fixture_return() -> None:
    base = json.loads(BASE_CONFIG.read_text())
    _config, trace, evidence = compile_h1_scenario(non_holdout_fixtures()[0], base)

    assert len(trace.pressure_stages) == 2
    second_pressure = trace.pressure_stages[1].planned_arrival_offset_seconds
    first_return = min(
        request.planned_arrival_offset_seconds for request in trace.requests if request.is_terminal
    )
    assert second_pressure < first_return
    assert evidence["pressure_contract"]["stage_count"] == 2


def test_non_holdout_campaign_round_trips_all_traces(tmp_path: Path) -> None:
    path = materialize_fidelity_campaign(BASE_CONFIG, tmp_path / "fixtures")
    manifest = json.loads(path.read_text())

    assert manifest["campaign_kind"] == "NON_HOLDOUT_FIDELITY_VALIDATION"
    assert len(manifest["fixtures"]) == 2
    for item in manifest["fixtures"]:
        trace = load_phase2_trace(path.parent / f"{item['scenario_id']}.trace.json")
        assert trace.pressure_stages
        assert len({request.program_id for request in trace.requests}) >= 2
