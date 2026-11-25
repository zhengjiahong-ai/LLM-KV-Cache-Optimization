"""Tests for the Phase 5 Formal Protocol contracts and schema validation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "probes" / "phase5_formal_protocol" / "validate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("phase5_formal_validate", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _protocol():
    return json.loads(
        (ROOT / "configs/phase5/phase5-formal-protocol-v1.json").read_text(encoding="utf-8")
    )


def _schema():
    return json.loads(
        (ROOT / "configs/phase5/schema/phase5-formal-protocol-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )


def test_valid_protocol_and_contracts() -> None:
    module = _load_module()
    result = module.validate_repository(ROOT)
    assert result["execution_authorized"] is False
    assert result["systems"] == [
        "A1_ORIGINAL",
        "A3_SUFFIX",
        "CONTINUUM_ADAPTED",
        "CONTINUUM_OFFICIAL",
        "DVA_ER_V1",
        "NATIVE",
    ]
    assert result["manifest_schema"] == "valid"


def test_rejects_execution_authorization() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["execution_authorized"] = True
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "non-executable" in str(error) or "schema" in str(error)
    else:
        raise AssertionError("authorized protocol was accepted")


def test_rejects_wrong_system_set() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["systems"] = protocol["systems"][:3]
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "six registered" in str(error) or "schema" in str(error)
    else:
        raise AssertionError("three-system protocol was accepted")


def test_rejects_bad_sample_bounds() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["workload"]["sample_plan"]["groups_per_stratum_min"] = 20
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "sample-size" in str(error)
    else:
        raise AssertionError("invalid sample bounds were accepted")


def test_rejects_missing_unresolved_decisions() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["unresolved"] = protocol["unresolved"][:-1]
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "unresolved" in str(error)
    else:
        raise AssertionError("missing unresolved decisions were accepted")


def test_rejects_missing_primary_contrast() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["statistics"]["primary_contrasts"] = protocol["statistics"]["primary_contrasts"][:2]
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "contrasts" in str(error)
    else:
        raise AssertionError("two-contrast protocol was accepted")


def test_rejects_session_below_four_turns() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["workload"]["min_turns_per_session"] = 3
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "four turns" in str(error) or "4 was expected" in str(error)
    else:
        raise AssertionError("three-turn qualification was accepted")


def test_protocol_has_no_additional_session_turn_ceiling() -> None:
    protocol = _protocol()
    assert protocol["workload"]["min_turns_per_session"] == 4
    assert "max_turns_per_session" not in protocol["workload"]


def test_rejects_reintroduced_session_turn_ceiling() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["workload"]["max_turns_per_session"] = 16
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "schema" in str(error) or "turn ceiling" in str(error)
    else:
        raise AssertionError("legacy fixed Turn ceiling was accepted")


def test_rejects_prompt_plus_generation_over_context() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["workload"]["max_prompt_tokens"] = 32768
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "prompt plus generation" in str(error) or "32640 was expected" in str(error)
    else:
        raise AssertionError("over-context prompt was accepted")


def test_rejects_prematurely_frozen_dva_candidate() -> None:
    module = _load_module()
    protocol = _protocol()
    for system in protocol["systems"]:
        if system["id"] == "DVA_ER_V1":
            system["status"] = "FROZEN"
            break
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "DVA-ER" in str(error) or "schema" in str(error)
    else:
        raise AssertionError("prematurely frozen candidate was accepted")


def test_rejects_budget_that_differs_from_m1_frozen_swe_ceiling() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["calibration"]["gpu_hours_maximum"] = 31
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "30.8 hours" in str(error)
    else:
        raise AssertionError("non-frozen SWE GPU budget was accepted")


def test_candidate_evaluation_fixtures_are_complete() -> None:
    module = _load_module()
    result = module.validate_candidate_fixtures(ROOT)
    assert result["cases"] == 7
    assert result["status"] == "CONTRACT_FIXTURES_ONLY_NOT_ALGORITHM_RESULTS"
    cases = {
        row["id"]: row
        for row in json.loads(
            (ROOT / "configs/phase5/fixtures/phase5-candidate-evaluation-cases.json").read_text(
                encoding="utf-8"
            )
        )["cases"]
    }
    assert cases["SCORE_RANK_INVERSION"]["expected"]["pairwise_rank_inversion"] is True
    assert cases["DIFFERENT_VICTIM_SET"]["expected"]["victim_set_divergence"] is True
    assert (
        cases["SAME_ENTRY_RANK_DIFFERENT_VICTIM_RISK"]["expected"]["dva_selection_can_diverge"]
        is True
    )
    assert cases["NATIVE_LRU_TIE_BREAK"]["expected"]["a0_tie_break_reproduced"] is True


def test_rejects_historical_gain_as_dva_gate() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["candidate_family"]["dva_er_selection_gate"][
        "full_trajectory_positive_gain_required"
    ] = True
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "historical" in str(error) or "schema" in str(error)
    else:
        raise AssertionError("historical positive gain was accepted as a gate")


def test_rejects_non_latin_square_arm_order() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["replay"]["execution_order"]["design"] = "RANDOM"
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "Latin" in str(error) or "schema" in str(error)
    else:
        raise AssertionError("non-Latin arm order was accepted")


def test_rejects_missing_dva_vs_a1_contrast() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["statistics"]["primary_families"]["CANDIDATE_MECHANISM"].remove("DVA_vs_A1")
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "DVA-vs-A1" in str(error) or "six contrasts" in str(error)
    else:
        raise AssertionError("missing DVA-vs-A1 contrast was accepted")


def test_rejects_homogeneity_test_pooling_switch() -> None:
    module = _load_module()
    protocol = _protocol()
    protocol["statistics"]["variance_model"]["homogeneity_test"] = True
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "homogeneity" in str(error)
    else:
        raise AssertionError("homogeneity-test pooling switch was accepted")


def test_rejects_obsolete_common_pooled_df_7() -> None:
    module = _load_module()
    protocol = _protocol()
    variance = protocol["statistics"]["variance_model"]
    variance["df_between"] = 7
    variance["pooled_df"] = 7
    try:
        module.validate_protocol(protocol, _schema())
    except ValueError as error:
        assert "variance contract" in str(error) or "pooled_df" in str(error)
    else:
        raise AssertionError("obsolete pooled df=7 was accepted")


def test_cross_contract_requires_exact_df6_df16_and_bootstrap_seed() -> None:
    docs = _contract_docs()
    docs["calibration"]["variance_model"]["df_within"] = 15
    try:
        _cross_validate(docs)
    except ValueError as error:
        assert "variance contract" in str(error)
    else:
        raise AssertionError("changed within-group df was accepted")


def _contract_docs():
    return {
        "protocol": _protocol(),
        "calibration": json.loads(
            (ROOT / "configs/phase5/phase5-calibration-sample-size-contract-v1.json").read_text(
                encoding="utf-8"
            )
        ),
        "family": json.loads(
            (ROOT / "configs/phase5/phase5-cost-aware-candidate-v1.json").read_text(
                encoding="utf-8"
            )
        ),
        "evaluation": json.loads(
            (ROOT / "configs/phase5/phase5-candidate-evaluation-contract-v1.json").read_text(
                encoding="utf-8"
            )
        ),
        "metrics": json.loads(
            (ROOT / "configs/phase5/phase5-metrics-contract-v1.json").read_text(encoding="utf-8")
        ),
        "workload_qualification": json.loads(
            (
                ROOT
                / "configs/phase5/phase5-workload-qualification-contract-v1.json"
            ).read_text(encoding="utf-8")
        ),
    }


def _cross_validate(docs) -> None:
    module = _load_module()
    module.validate_cross_documents(
        docs["protocol"],
        docs["calibration"],
        docs["family"],
        docs["evaluation"],
        docs["metrics"],
        docs["workload_qualification"],
    )


def test_cross_contract_rejects_wrong_alpha() -> None:
    docs = _contract_docs()
    docs["calibration"]["sample_size_formula"]["alpha_per_test"] = 0.01
    try:
        _cross_validate(docs)
    except ValueError as error:
        assert "alpha" in str(error)
    else:
        raise AssertionError("inconsistent alpha was accepted")


def test_cross_contract_rejects_two_stratum_variance_model() -> None:
    docs = _contract_docs()
    docs["calibration"]["variance_model"]["model"] = (
        "d_g_r = mu + tau_s + b_g + epsilon_g_r"
    )
    try:
        _cross_validate(docs)
    except ValueError as error:
        assert "model" in str(error)
    else:
        raise AssertionError("two-stratum variance model was accepted")


def test_cross_contract_rejects_second_overhead_factor() -> None:
    docs = _contract_docs()
    docs["calibration"]["resource_budget"]["overhead_factor"] = 1.2
    try:
        _cross_validate(docs)
    except ValueError as error:
        assert "overhead" in str(error)
    else:
        raise AssertionError("second overhead factor was accepted")


def test_cross_contract_rejects_preheat_mismatch() -> None:
    docs = _contract_docs()
    docs["protocol"]["replay"]["preheat"]["warmup_evidence_required"] = True
    try:
        _cross_validate(docs)
    except ValueError as error:
        assert "preheat" in str(error)
    else:
        raise AssertionError("preheat mismatch was accepted")


def test_contracts_and_manifest_schema_are_valid() -> None:
    module = _load_module()
    contracts_schema = json.loads(
        (ROOT / "configs/phase5/schema/phase5-contracts-v1.schema.json").read_text(encoding="utf-8")
    )
    contracts = module.validate_contracts(ROOT, contracts_schema)
    assert set(contracts) == {
        "metrics",
        "workload_qualification",
        "calibration_sample_size",
        "cost_aware_candidate_family",
        "candidate_evaluation",
    }
    module.validate_manifest_schema(ROOT)
