"""Validate the Phase 5 Formal Protocol JSON, schema and contracts.

This is a CPU-only contract validator.  It does not authorize GPU execution and
does not load or fabricate campaign outcomes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import jsonschema

PROTOCOL_PATH = Path("configs/phase5/phase5-formal-protocol-v1.json")
PROTOCOL_SCHEMA_PATH = Path("configs/phase5/schema/phase5-formal-protocol-v1.schema.json")
CONTRACTS_SCHEMA_PATH = Path("configs/phase5/schema/phase5-contracts-v1.schema.json")
MANIFEST_SCHEMA_PATH = Path("configs/phase5/schema/phase5-campaign-manifest-v1.schema.json")
FIXTURE_PATH = Path("configs/phase5/fixtures/phase5-candidate-evaluation-cases.json")
FIXTURE_SCHEMA_PATH = Path(
    "configs/phase5/schema/phase5-candidate-evaluation-fixtures-v1.schema.json"
)
CONTRACT_PATHS = {
    "metrics": Path("configs/phase5/phase5-metrics-contract-v1.json"),
    "workload_qualification": Path("configs/phase5/phase5-workload-qualification-contract-v1.json"),
    "calibration_sample_size": Path(
        "configs/phase5/phase5-calibration-sample-size-contract-v1.json"
    ),
    "cost_aware_candidate_family": Path("configs/phase5/phase5-cost-aware-candidate-v1.json"),
    "candidate_evaluation": Path("configs/phase5/phase5-candidate-evaluation-contract-v1.json"),
}
SYSTEM_IDS = {
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_protocol(protocol: dict[str, Any], schema: dict[str, Any]) -> None:
    jsonschema.Draft202012Validator.check_schema(schema)
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(protocol),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ValueError(
            "protocol schema validation failed: " + "; ".join(error.message for error in errors[:5])
        )

    if protocol["execution_authorized"] is not False:
        raise ValueError("formal protocol must remain non-executable before M1 freeze")
    system_ids = {system["id"] for system in protocol["systems"]}
    if system_ids != SYSTEM_IDS or len(protocol["systems"]) != 6:
        raise ValueError("protocol must define exactly the six registered systems")

    sample = protocol["workload"]["sample_plan"]
    if not (
        sample["groups_per_stratum_min"]
        <= sample["groups_per_stratum_target"]
        <= sample["groups_per_stratum_max"]
    ):
        raise ValueError("sample-size bounds are not ordered")
    if sample["calibration_groups_per_stratum"] >= sample["groups_per_stratum_min"]:
        raise ValueError("calibration Groups must be disjoint from the formal Group minimum")
    if sample["formal_repeats"] != 2 or sample["calibration_repeats"] != 3:
        raise ValueError("frozen repeat counts must be formal=2 and calibration=3")
    if protocol["workload"]["min_turns_per_session"] < 4:
        raise ValueError("formal Sessions must have at least four turns")
    if (
        protocol["workload"]["max_prompt_tokens"] + protocol["workload"]["max_generation_tokens"]
        > protocol["workload"]["max_prompt_plus_generation_tokens"]
    ):
        raise ValueError("prompt plus generation exceeds the frozen max_model_len")
    if not protocol["workload"]["generation_config"]:
        raise ValueError("generation configuration must be frozen")
    if protocol["workload"]["right_censoring"]["missing_future_turns"] != "NOT_IMPUTED":
        raise ValueError("right-censored future turns must not be imputed")
    candidate_family = protocol["candidate_family"]
    family_candidates = candidate_family["candidates"]
    if family_candidates != ["A1_ORIGINAL", "A3_SUFFIX", "DVA_ER_V1"]:
        raise ValueError("Cost-Aware family must contain A1, A3 and DVA-ER")
    if candidate_family["reference_system"] != "CONTINUUM_ADAPTED":
        raise ValueError("A0 must be the common Cost-Aware reference")
    if len(candidate_family["comparison_matrix"]) < 7:
        raise ValueError("candidate comparison matrix is incomplete")
    if len(candidate_family["stages"]) != 3:
        raise ValueError("all three candidate evaluation stages are required")
    if candidate_family["data_partitions"]["historical_archive"] != (
        "EXPLORATORY_AND_REPRODUCTION_ONLY"
    ):
        raise ValueError("historical archive cannot be confirmatory")
    if candidate_family["data_partitions"]["formal_cohort"] != "CONFIRMATORY_ONLY":
        raise ValueError("formal cohort must be confirmatory only")
    if candidate_family["dva_er"]["future_information_used"] is not False:
        raise ValueError("DVA-ER cannot use future information")
    if candidate_family["dva_er"]["missing_evidence"] != "FAIL_CLOSED":
        raise ValueError("DVA-ER must fail closed on missing evidence")
    gate = candidate_family["dva_er_selection_gate"]
    if gate["status"] != "NOT_EXECUTED":
        raise ValueError("DVA-ER CPU selection gate must not be pre-completed")
    if gate["full_trajectory_positive_gain_required"] is not False:
        raise ValueError("historical positive gain cannot be a DVA-ER gate")
    if gate["historical_archive_gain"] != "REPORT_ONLY_NOT_A_GATE":
        raise ValueError("historical gain must be report-only")
    if len(gate["required"]) < 7:
        raise ValueError("DVA-ER correctness gate is incomplete")
    candidates = {row["id"]: row for row in protocol["systems"]}
    if candidates["A1_ORIGINAL"]["status"] != "FROZEN_LEGACY":
        raise ValueError("A1 original must remain a frozen legacy implementation")
    if candidates["A3_SUFFIX"]["status"] != "FROZEN_LEGACY":
        raise ValueError("A3 suffix must remain a frozen legacy implementation")
    if candidates["DVA_ER_V1"]["status"] != "PROVISIONAL_NOT_FROZEN":
        raise ValueError("DVA-ER must remain provisional until the CPU gate")

    if protocol["metrics"]["primary"]["id"] != "recomputed_tokens_E_minus_C":
        raise ValueError("primary metric must be recomputed_tokens_E_minus_C")
    contrasts = protocol["statistics"]["primary_contrasts"]
    if len(contrasts) != 8 or len(set(contrasts)) != 8:
        raise ValueError("eight unique primary contrasts are required")
    families = protocol["statistics"]["primary_families"]
    if len(families["CANDIDATE_MECHANISM"]) != 6:
        raise ValueError("candidate mechanism family must contain six contrasts")
    if len(families["SYSTEM_CONTEXT"]) != 2:
        raise ValueError("system context family must contain two contrasts")
    if set(families["CANDIDATE_MECHANISM"] + families["SYSTEM_CONTEXT"]) != set(contrasts):
        raise ValueError("primary contrast families do not cover the registered tests")
    if "DVA_vs_A1" not in families["CANDIDATE_MECHANISM"]:
        raise ValueError("DVA-vs-A1 contrast is missing")
    if protocol["statistics"]["multiplicity"] != "HOLM_WITHIN_EACH_FAMILY_PER_STRATUM":
        raise ValueError("multiplicity must be Holm within family and stratum")
    if protocol["statistics"]["no_optional_stopping"] is not True:
        raise ValueError("optional stopping is prohibited")
    if protocol["statistics"]["sample_size_uses_noncentral_t_not_z"] is not True:
        raise ValueError("sample size must use noncentral t, not z")
    covariance = protocol["statistics"]["variance_model"]
    if covariance["contrast_covariance_required"] is not True:
        raise ValueError("contrast covariance must be estimated")
    if covariance["contrast_covariance_size"] != 8:
        raise ValueError("contrast covariance must cover all eight tests")
    if covariance["homogeneity_test"] is not False:
        raise ValueError("no homogeneity-test-based pooling switch is allowed")
    if "FIXED_COMMON_MIXED_MODEL" not in covariance["pooling_rule"]:
        raise ValueError("variance pooling must be a fixed pre-registered model")
    if protocol["statistics"]["mde_pre_registration_order"][-1] != "FREEZE_VALUE_BEFORE_FORMAL":
        raise ValueError("MDE value must be frozen before formal execution")

    unresolved_ids = {row["id"] for row in protocol["unresolved"]}
    required_unresolved = {
        "U1_COST_AWARE_CANDIDATE_FAMILY",
        "U2_CONTINUUM_ADAPTED_SCHEDULER_SCOPE",
        "U3_OFFICIAL_ENVIRONMENT_COMPATIBILITY",
        "U4_BFCL_TRACE_ACQUISITION",
        "U5_ARRIVAL_RATE_AND_SEED",
        "U6_CALIBRATION_AND_GPU_BUDGET",
        "U7_CENSORED_SESSION_POLICY",
    }
    if unresolved_ids != required_unresolved:
        raise ValueError("unresolved M1 decision set is incomplete")

    calibration = protocol["calibration"]
    if calibration["groups_per_stratum"] != 4 or calibration["runs_total"] != 144:
        raise ValueError("calibration must be 4 Groups/stratum and 144 six-arm runs")
    if calibration["systems"] != 6:
        raise ValueError("calibration must include all six systems")
    if calibration["sample_size_min_per_stratum"] != 8:
        raise ValueError("minimum formal Groups/stratum is 8")
    if calibration["sample_size_max_per_stratum"] != 16:
        raise ValueError("maximum formal Groups/stratum is 16")
    if calibration["formal_runs_at_min"] != 192:
        raise ValueError("six-arm formal minimum must be 192 runs")
    if calibration["formal_runs_at_max"] != 384:
        raise ValueError("six-arm formal maximum must be 384 runs")
    if calibration["sample_size_contrast_family"] != "SIX_CANDIDATE_CONTRASTS_PER_STRATUM":
        raise ValueError("sample size must use the six candidate contrasts")
    if abs(calibration["sample_size_alpha_per_test"] - 0.05 / 6) > 1e-12:
        raise ValueError("candidate-family alpha must be 0.05/6")
    if calibration["gpu_hours_minimum"] < 72:
        raise ValueError("six-arm GPU budget cannot support the minimum sample within 72 hours")
    if calibration["gpu_hours_maximum"] < calibration["gpu_hours_minimum"]:
        raise ValueError("GPU budget range is inverted")
    if calibration["formula_result_below_min"] != "USE_8_AND_REPORT_VARIANCE_UNCERTAINTY":
        raise ValueError("formula-below-minimum rule must use 8, not stop")
    if calibration["if_budget_cannot_support_minimum"] != "NOT_FEASIBLE":
        raise ValueError("budget below the minimum sample must stop")
    if not protocol["replay"]["execution_order"]["design"]:
        raise ValueError("execution order must be pre-registered")
    if protocol["replay"]["execution_order"]["design"] != "BALANCED_LATIN_SQUARE":
        raise ValueError("formal arm order must be a balanced Latin square")
    if protocol["replay"]["preheat"]["mode"] != "NONE":
        raise ValueError("formal preheat must be NONE")
    if protocol["replay"]["isolation"]["cross_run_kv_reuse"] is not False:
        raise ValueError("cross-run KV reuse is prohibited")
    if protocol["replay"]["isolation"]["cross_run_apc_reuse"] is not False:
        raise ValueError("cross-run APC reuse is prohibited")
    if protocol["replay"]["execution_order"]["outcome_based_reordering"] is not False:
        raise ValueError("outcome-based arm reordering is prohibited")


def validate_contracts(repository: Path, schema: dict[str, Any]) -> dict[str, Any]:
    jsonschema.Draft202012Validator.check_schema(schema)
    results: dict[str, Any] = {}
    for name, relative in CONTRACT_PATHS.items():
        document = _load(repository / relative)
        errors = sorted(
            jsonschema.Draft202012Validator(schema).iter_errors(document),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            raise ValueError(
                f"{name} contract schema validation failed: "
                + "; ".join(error.message for error in errors[:5])
            )
        results[name] = document["schema_version"]
    return results


def validate_manifest_schema(repository: Path) -> None:
    manifest_schema = _load(repository / MANIFEST_SCHEMA_PATH)
    jsonschema.Draft202012Validator.check_schema(manifest_schema)
    example = {
        "schema_version": "phase5.campaign_manifest.v1",
        "protocol_id": "phase5-formal-six-system-trace-replay-v1",
        "protocol_sha256": "0" * 64,
        "run_id": "P5F-EXAMPLE",
        "group_id": "G000",
        "system_id": "NATIVE",
        "system_revision": "PINNED",
        "stratum": "SWE_BENCH",
        "repeat_index": 0,
        "workload_seal_sha256": "0" * 64,
        "arrival_realization_sha256": "0" * 64,
        "model_revision": "PINNED",
        "tokenizer_revision": "PINNED",
        "sampling_parameters_sha256": "0" * 64,
        "engine_configuration_sha256": "0" * 64,
        "generation_config_sha256": "0" * 64,
        "execution_order_index": 0,
        "engine_instance_id": "ENGINE-EXAMPLE-0",
        "isolation_preflight": {
            "new_process": True,
            "new_engine": True,
            "cross_run_apc_reuse": False,
            "empty_cache_verified": True,
        },
        "preheat_mode": "NONE",
        "actual_enqueue_sequence_sha256": "0" * 64,
        "evidence": {
            "planned_events_sha256": "0" * 64,
            "native_events_sha256": "0" * 64,
            "terminal_events_sha256": "0" * 64,
            "exposure_events_sha256": "0" * 64,
            "pressure_events_sha256": None,
        },
        "metrics": {
            "recomputed_tokens_E_minus_C": 0,
            "coverage": {
                "requests_expected": 24,
                "requests_observed": 24,
                "requests_valid": 24,
                "requests_missing": 0,
            },
        },
        "status": "PASS",
        "runner_version": "PHASE5_FORMAL_RUNNER_V1",
        "evaluator_version": "PHASE5_EVALUATOR_V1",
        "archive_sha256": "0" * 64,
        "created_at": "2026-11-18T00:00:00+08:00",
    }
    errors = sorted(
        jsonschema.Draft202012Validator(manifest_schema).iter_errors(example),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ValueError(
            "manifest schema example validation failed: "
            + "; ".join(error.message for error in errors[:5])
        )


def validate_candidate_fixtures(repository: Path) -> dict[str, Any]:
    schema = _load(repository / FIXTURE_SCHEMA_PATH)
    document = _load(repository / FIXTURE_PATH)
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ValueError(
            "candidate fixture validation failed: "
            + "; ".join(error.message for error in errors[:5])
        )
    cases = {row["id"]: row for row in document["cases"]}
    if set(cases) != {
        "MULTIPLE_LEGAL_CANDIDATES",
        "SCORE_RANK_INVERSION",
        "DIFFERENT_VICTIM_SET",
        "SAME_ENTRY_RANK_DIFFERENT_VICTIM_RISK",
        "MISSING_EVIDENCE",
        "FUTURE_INFORMATION_UNAVAILABLE",
        "NATIVE_LRU_TIE_BREAK",
    }:
        raise ValueError("candidate fixture case set is incomplete")
    if cases["FUTURE_INFORMATION_UNAVAILABLE"]["expected"]["future_fields_rejected"] is not True:
        raise ValueError("future-information fixture must reject future fields")
    if cases["MISSING_EVIDENCE"]["expected"]["fail_closed"] is not True:
        raise ValueError("missing-evidence fixture must fail closed")
    return {"cases": len(cases), "status": document["status"]}


CANDIDATE_CONTRASTS = [
    "A1_vs_A0",
    "A3_vs_A0",
    "DVA_vs_A0",
    "A3_vs_A1",
    "DVA_vs_A1",
    "DVA_vs_A3",
]
SYSTEM_CONTRASTS = ["NATIVE_vs_A0", "OFFICIAL_vs_A0"]


def validate_cross_documents(
    protocol: dict[str, Any],
    calibration: dict[str, Any],
    family: dict[str, Any],
    evaluation: dict[str, Any],
    metrics: dict[str, Any],
) -> None:
    """Check the statistical and budget definitions agree across files."""

    expected_all = CANDIDATE_CONTRASTS + SYSTEM_CONTRASTS
    stats = protocol["statistics"]
    if stats["primary_contrasts"] != expected_all:
        raise ValueError("protocol contrasts do not match the registered six-plus-two family")
    if stats["primary_families"]["CANDIDATE_MECHANISM"] != CANDIDATE_CONTRASTS:
        raise ValueError("protocol candidate family is not the six registered contrasts")
    if stats["primary_families"]["SYSTEM_CONTEXT"] != SYSTEM_CONTRASTS:
        raise ValueError("protocol system context family is not the two registered contrasts")
    if stats["primary_family_size"] != 8:
        raise ValueError("protocol primary family size must be eight")
    if abs(stats["sample_size_alpha_per_test"] - 0.05 / 6) > 1e-12:
        raise ValueError("protocol candidate alpha must be 0.05/6")
    if stats["variance_model"]["contrast_covariance_size"] != 8:
        raise ValueError("protocol covariance must be 8x8")
    if stats["variance_model"]["homogeneity_test"] is not False:
        raise ValueError("protocol variance model must not use a homogeneity test")

    if calibration["power"]["primary_contrasts"] != 6:
        raise ValueError("calibration must size six candidate contrasts")
    if calibration["power"]["family_size"] != 6:
        raise ValueError("calibration candidate family must have six tests")
    if abs(calibration["sample_size_formula"]["alpha_per_test"] - 0.05 / 6) > 1e-12:
        raise ValueError("calibration alpha must be 0.05/6")
    if calibration["variance_model"]["contrast_covariance_size"] != 8:
        raise ValueError("calibration covariance must be 8x8")
    if calibration["variance_model"]["homogeneity_test"] is not False:
        raise ValueError("calibration variance model must not use a homogeneity test")
    model = calibration["variance_model"]["model"]
    if "tau_s" not in model or "b_{g(s)}" not in model:
        raise ValueError(
            "calibration model must include stratum fixed effect and Group random effect"
        )
    if "homogeneity" in calibration["variance_model"]["low_df_warning"].lower():
        raise ValueError("calibration low-df rule still references homogeneity testing")
    if calibration["analysis_contract"]["primary_family"] != CANDIDATE_CONTRASTS:
        raise ValueError("calibration primary family does not match protocol")
    if calibration["analysis_contract"]["primary_system_context_family"] != SYSTEM_CONTRASTS:
        raise ValueError("calibration system context family does not match protocol")
    if calibration["formal_runs"]["systems"] != 6:
        raise ValueError("calibration formal_runs must cover six systems")
    if (
        calibration["formal_runs"]["runs_at_min"] != 192
        or calibration["formal_runs"]["runs_at_max"] != 384
    ):
        raise ValueError("calibration formal run counts do not match six arms")
    if len(calibration["resource_budget"]["per_system_p95_fields"]) != 6:
        raise ValueError("calibration must define six per-system p95 fields")
    p95 = calibration["resource_budget"]["per_system_p95_seconds"]
    if set(p95) != set(calibration["resource_budget"]["per_system_p95_fields"]):
        raise ValueError("per-system p95 values do not match the six systems")
    if (
        "calibration_run_p95_seconds" in calibration["resource_budget"]
        or "formal_run_p95_seconds" in calibration["resource_budget"]
    ):
        raise ValueError("legacy global p95 string remains")
    if "overhead_factor" in calibration["resource_budget"]:
        raise ValueError("calibration must not use a second overhead factor")
    if calibration["resource_budget"]["failure_reserve_fraction"] != 0.10:
        raise ValueError("calibration failure reserve must be exactly 10%")
    if (
        calibration["resource_budget"]["budget_envelope_minimum_hours"]
        != protocol["calibration"]["gpu_hours_minimum"]
    ):
        raise ValueError("protocol/calibration minimum budget disagree")
    if (
        calibration["resource_budget"]["budget_envelope_maximum_hours"]
        != protocol["calibration"]["gpu_hours_maximum"]
    ):
        raise ValueError("protocol/calibration maximum budget disagree")

    if family["candidates"] and [row["id"] for row in family["candidates"]] != [
        "A1_ORIGINAL",
        "A3_SUFFIX",
        "DVA_ER_V1",
    ]:
        raise ValueError("candidate family does not contain the three candidates")
    if family["dva_er_selection_gate"]["full_trajectory_positive_gain_required"] is not False:
        raise ValueError("candidate family still requires a positive historical gain")
    if evaluation.get("candidate_contrasts", []) != CANDIDATE_CONTRASTS:
        raise ValueError("candidate evaluation contrasts do not match protocol")
    if evaluation["common_inputs"]["candidate_specific_data_selection"] != "FORBIDDEN":
        raise ValueError("candidate evaluation allows candidate-specific data")
    if metrics["candidate_evaluation_contract"] != "phase5.candidate_evaluation.v1":
        raise ValueError("metrics contract does not bind candidate evaluation")

    if protocol["entry_gates"].count("G2_SIX_SYSTEM_FREEZE") != 1:
        raise ValueError("entry gates must contain exactly one G2 six-system freeze")
    if "G2_FOUR_SYSTEM_FREEZE" in protocol["entry_gates"]:
        raise ValueError("legacy four-system entry gate remains")
    preheat = protocol["replay"]["preheat"]
    if preheat["mode"] != "NONE" or preheat["warmup_evidence_required"] is not False:
        raise ValueError("preheat must be NONE with no warmup evidence requirement")


def validate_cross_contracts(protocol: dict[str, Any], repository: Path) -> None:
    documents = {name: _load(repository / relative) for name, relative in CONTRACT_PATHS.items()}
    validate_cross_documents(
        protocol,
        documents["calibration_sample_size"],
        documents["cost_aware_candidate_family"],
        documents["candidate_evaluation"],
        documents["metrics"],
    )


def validate_repository(repository: Path) -> dict[str, Any]:
    repository = repository.resolve()
    protocol = _load(repository / PROTOCOL_PATH)
    schema = _load(repository / PROTOCOL_SCHEMA_PATH)
    validate_protocol(protocol, schema)
    contracts_schema = _load(repository / CONTRACTS_SCHEMA_PATH)
    contracts = validate_contracts(repository, contracts_schema)
    validate_cross_contracts(protocol, repository)
    validate_manifest_schema(repository)
    fixtures = validate_candidate_fixtures(repository)
    for reference in protocol["contracts"].values():
        if not isinstance(reference, str) or not reference:
            raise ValueError("contract reference must be a non-empty string")
    return {
        "status": protocol["status"],
        "systems": sorted(system["id"] for system in protocol["systems"]),
        "contracts": contracts,
        "fixtures": fixtures,
        "manifest_schema": "valid",
        "execution_authorized": protocol["execution_authorized"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    result = validate_repository(args.repository)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
