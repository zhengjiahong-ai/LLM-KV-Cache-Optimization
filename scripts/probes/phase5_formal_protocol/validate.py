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
CONTRACT_PATHS = {
    "metrics": Path("configs/phase5/phase5-metrics-contract-v1.json"),
    "workload_qualification": Path("configs/phase5/phase5-workload-qualification-contract-v1.json"),
    "calibration_sample_size": Path(
        "configs/phase5/phase5-calibration-sample-size-contract-v1.json"
    ),
    "cost_aware_candidate": Path("configs/phase5/phase5-cost-aware-candidate-v1.json"),
}
SYSTEM_IDS = {"NATIVE", "CONTINUUM_OFFICIAL", "CONTINUUM_ADAPTED", "COST_AWARE"}


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
    if system_ids != SYSTEM_IDS or len(protocol["systems"]) != 4:
        raise ValueError("protocol must define exactly the four registered systems")

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
    candidate = protocol["cost_aware_candidate"]
    if candidate["id"] != "DVA_ER_V1" or candidate["status"] != "PROVISIONAL_NOT_FROZEN":
        raise ValueError("Cost-Aware candidate must be the provisional DVA_ER_V1 design")
    if candidate["selection_gate"]["status"] != "NOT_EXECUTED":
        raise ValueError("candidate selection gate must not be pre-completed")

    if protocol["metrics"]["primary"]["id"] != "recomputed_tokens_E_minus_C":
        raise ValueError("primary metric must be recomputed_tokens_E_minus_C")
    contrasts = protocol["statistics"]["primary_contrasts"]
    if len(contrasts) != 3 or len(set(contrasts)) != 3:
        raise ValueError("three unique primary contrasts are required")
    if protocol["statistics"]["primary_family_size"] != 6:
        raise ValueError("primary multiplicity family must cover 3 contrasts x 2 strata")
    if protocol["statistics"]["multiplicity"] != "HOLM":
        raise ValueError("primary multiplicity must be Holm")
    if protocol["statistics"]["no_optional_stopping"] is not True:
        raise ValueError("optional stopping is prohibited")
    if protocol["statistics"]["sample_size_uses_noncentral_t_not_z"] is not True:
        raise ValueError("sample size must use noncentral t, not z")
    covariance = protocol["statistics"]["variance_model"]
    if covariance["contrast_covariance_required"] is not True:
        raise ValueError("contrast covariance must be estimated")
    if protocol["statistics"]["mde_pre_registration_order"][-1] != "FREEZE_VALUE_BEFORE_FORMAL":
        raise ValueError("MDE value must be frozen before formal execution")

    unresolved_ids = {row["id"] for row in protocol["unresolved"]}
    required_unresolved = {
        "U1_COST_AWARE_CANDIDATE",
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
    if calibration["groups_per_stratum"] != 4 or calibration["runs_total"] != 96:
        raise ValueError("calibration must be 4 Groups/stratum and 96 runs")
    if calibration["sample_size_min_per_stratum"] != 8:
        raise ValueError("minimum formal Groups/stratum is 8")
    if calibration["sample_size_max_per_stratum"] != 16:
        raise ValueError("maximum formal Groups/stratum is 16")
    if calibration["gpu_hours_minimum"] < 48:
        raise ValueError("GPU budget cannot support the minimum sample within 48 hours")
    if calibration["gpu_hours_maximum"] < calibration["gpu_hours_minimum"]:
        raise ValueError("GPU budget range is inverted")
    if calibration["formula_result_below_min"] != "USE_8_AND_REPORT_VARIANCE_UNCERTAINTY":
        raise ValueError("formula-below-minimum rule must use 8, not stop")
    if calibration["if_budget_cannot_support_minimum"] != "NOT_FEASIBLE":
        raise ValueError("budget below the minimum sample must stop")
    if not protocol["replay"]["execution_order"]["design"]:
        raise ValueError("execution order must be pre-registered")
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
        "protocol_id": "phase5-formal-four-system-trace-replay-v1",
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


def validate_repository(repository: Path) -> dict[str, Any]:
    repository = repository.resolve()
    protocol = _load(repository / PROTOCOL_PATH)
    schema = _load(repository / PROTOCOL_SCHEMA_PATH)
    validate_protocol(protocol, schema)
    contracts_schema = _load(repository / CONTRACTS_SCHEMA_PATH)
    contracts = validate_contracts(repository, contracts_schema)
    validate_manifest_schema(repository)
    for reference in protocol["contracts"].values():
        if not isinstance(reference, str) or not reference:
            raise ValueError("contract reference must be a non-empty string")
    return {
        "status": protocol["status"],
        "systems": sorted(system["id"] for system in protocol["systems"]),
        "contracts": contracts,
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
