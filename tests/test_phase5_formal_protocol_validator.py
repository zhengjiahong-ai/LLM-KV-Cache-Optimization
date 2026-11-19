from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_formal_protocol_validator import (
    Phase5ProtocolValidationError,
    require_execution_ready,
    validate_campaign_manifest_set,
    validate_protocol_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "phase5"
CONTRACT_PATHS = {
    "metrics": CONFIG / "phase5-metrics-contract-v1.json",
    "workload_qualification": CONFIG / "phase5-workload-qualification-contract-v1.json",
    "calibration_sample_size": CONFIG
    / "phase5-calibration-sample-size-contract-v1.json",
    "cost_aware_candidate_family": CONFIG / "phase5-cost-aware-candidate-v1.json",
    "candidate_evaluation": CONFIG / "phase5-candidate-evaluation-contract-v1.json",
}
SYSTEM_IDS = (
    "NATIVE",
    "CONTINUUM_OFFICIAL",
    "CONTINUUM_ADAPTED",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
)


def _bundle():
    return validate_protocol_bundle(
        protocol_path=CONFIG / "phase5-formal-protocol-v1.json",
        protocol_schema_path=CONFIG
        / "schema"
        / "phase5-formal-protocol-v1.schema.json",
        contract_paths=CONTRACT_PATHS,
        contracts_schema_path=CONFIG / "schema" / "phase5-contracts-v1.schema.json",
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _manifest(system_id: str) -> dict[str, object]:
    bundle = _bundle()
    return {
        "schema_version": "phase5.campaign_manifest.v1",
        "protocol_id": bundle.protocol["protocol_id"],
        "protocol_sha256": bundle.protocol_sha256,
        "run_id": f"g01-r0-{system_id.lower()}",
        "group_id": "g01",
        "system_id": system_id,
        "system_revision": f"revision-{system_id.lower()}",
        "stratum": "SWE_BENCH",
        "repeat_index": 0,
        "workload_seal_sha256": _digest("workload"),
        "arrival_realization_sha256": _digest("arrival"),
        "model_revision": "model-revision",
        "tokenizer_revision": "tokenizer-revision",
        "sampling_parameters_sha256": _digest("sampling"),
        "engine_configuration_sha256": _digest("engine"),
        "generation_config_sha256": _digest("generation"),
        "execution_order_index": 0,
        "engine_instance_id": f"engine-{system_id.lower()}",
        "isolation_preflight": {
            "new_process": True,
            "new_engine": True,
            "cross_run_apc_reuse": False,
            "empty_cache_verified": True,
        },
        "preheat_mode": "NONE",
        "actual_enqueue_sequence_sha256": _digest(system_id),
        "evidence": {
            "planned_events_sha256": _digest("planned"),
            "native_events_sha256": _digest(f"native-{system_id}"),
            "terminal_events_sha256": _digest(f"terminal-{system_id}"),
            "exposure_events_sha256": _digest(f"exposure-{system_id}"),
            "pressure_events_sha256": None,
        },
        "metrics": {
            "recomputed_tokens_E_minus_C": 0,
            "coverage": {
                "requests_expected": 8,
                "requests_observed": 8,
                "requests_valid": 8,
                "requests_missing": 0,
            },
        },
        "status": "PASS",
        "runner_version": "runner-v1",
        "evaluator_version": "evaluator-v1",
        "archive_sha256": _digest(f"archive-{system_id}"),
        "created_at": "2026-11-18T00:00:00+08:00",
    }


def _validate_manifests(manifests: list[dict[str, object]]) -> None:
    validate_campaign_manifest_set(
        manifests=manifests,
        manifest_schema=json.loads(
            (CONFIG / "schema" / "phase5-campaign-manifest-v1.schema.json").read_text()
        ),
        bundle=_bundle(),
        expected_workload_seal_sha256=_digest("workload"),
        expected_runtime_identity={
            "model_revision": "model-revision",
            "tokenizer_revision": "tokenizer-revision",
            "sampling_parameters_sha256": _digest("sampling"),
            "engine_configuration_sha256": _digest("engine"),
            "generation_config_sha256": _digest("generation"),
            "arrival_realization_sha256": _digest("arrival"),
        },
        expected_system_revisions={
            system_id: f"revision-{system_id.lower()}"
            for system_id in SYSTEM_IDS
        },
    )


def test_current_design_bundle_is_valid_but_not_executable() -> None:
    bundle = _bundle()
    assert bundle.protocol["status"] == "DESIGN_FROZEN_CANDIDATE"
    assert bundle.execution_ready is False
    with pytest.raises(Phase5ProtocolValidationError, match="execution_authorized=false"):
        require_execution_ready(bundle)


def test_bundle_rejects_wrong_frozen_contract_hash() -> None:
    bundle = _bundle()
    expected = dict(bundle.sha256)
    expected["metrics"] = "0" * 64
    with pytest.raises(Phase5ProtocolValidationError, match="metrics"):
        validate_protocol_bundle(
            protocol_path=CONFIG / "phase5-formal-protocol-v1.json",
            protocol_schema_path=CONFIG
            / "schema"
            / "phase5-formal-protocol-v1.schema.json",
            contract_paths=CONTRACT_PATHS,
            contracts_schema_path=CONFIG / "schema" / "phase5-contracts-v1.schema.json",
            expected_sha256=expected,
        )


def test_six_system_manifest_identity_passes() -> None:
    manifests = [_manifest(system_id) for system_id in SYSTEM_IDS]
    _validate_manifests(manifests)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows.pop(), "six systems"),
        (
            lambda rows: rows[1].__setitem__("system_id", "NATIVE"),
            "duplicate arm",
        ),
        (
            lambda rows: rows[2].__setitem__("workload_seal_sha256", _digest("other")),
            "workload seal",
        ),
        (
            lambda rows: rows[3].__setitem__("arrival_realization_sha256", _digest("other")),
            "runtime identity",
        ),
        (
            lambda rows: rows[1].__setitem__("group_id", "g02"),
            "not paired",
        ),
    ],
)
def test_manifest_consistency_fail_closed(mutation, message: str) -> None:
    manifests = [_manifest(system_id) for system_id in SYSTEM_IDS]
    mutation(manifests)
    with pytest.raises(Phase5ProtocolValidationError, match=message):
        _validate_manifests(copy.deepcopy(manifests))
