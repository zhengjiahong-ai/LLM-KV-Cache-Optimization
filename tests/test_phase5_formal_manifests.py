from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from kvopt.workload.phase5_formal_manifests import (
    Phase5ManifestError,
    build_archive_envelope,
    build_run_input_manifest,
    build_run_result_manifest,
    canonical_bytes,
    manifest_sha256,
    validate_archive_envelope,
    validate_run_input_manifest,
    validate_run_result_manifest,
)
from kvopt.workload.phase5_formal_protocol_validator import (
    Phase5ProtocolValidationError,
    ProtocolBundle,
    validate_protocol_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "phase5"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _candidate_bundle() -> ProtocolBundle:
    return validate_protocol_bundle(
        protocol_path=CONFIG / "phase5-formal-protocol-v1.json",
        protocol_schema_path=CONFIG
        / "schema"
        / "phase5-formal-protocol-v1.schema.json",
        contract_paths={
            "metrics": CONFIG / "phase5-metrics-contract-v1.json",
            "workload_qualification": CONFIG
            / "phase5-workload-qualification-contract-v1.json",
            "calibration_sample_size": CONFIG
            / "phase5-calibration-sample-size-contract-v1.json",
            "cost_aware_candidate_family": CONFIG
            / "phase5-cost-aware-candidate-v1.json",
            "candidate_evaluation": CONFIG
            / "phase5-candidate-evaluation-contract-v1.json",
        },
        contracts_schema_path=CONFIG / "schema" / "phase5-contracts-v1.schema.json",
    )


def _ready_bundle() -> ProtocolBundle:
    candidate = _candidate_bundle()
    protocol = copy.deepcopy(candidate.protocol)
    protocol["status"] = "M1_FROZEN"
    protocol["execution_authorized"] = True
    protocol["unresolved"] = []
    systems = {system["id"]: system for system in protocol["systems"]}
    systems["DVA_ER_V1"]["status"] = "FROZEN"
    systems["DVA_ER_V1"]["candidate_selection_gate"] = "PASS"
    systems["CONTINUUM_OFFICIAL"]["compatibility_status"] = "PASS"
    systems["CONTINUUM_ADAPTED"]["scheduler_conformance"] = "PASS"
    return ProtocolBundle(protocol, candidate.contracts, candidate.sha256)


def _input(bundle: ProtocolBundle | None = None):
    return build_run_input_manifest(
        bundle=bundle or _ready_bundle(),
        run_id="p5f-g01-r0-native",
        group_id="g01",
        stratum="SWE_BENCH",
        repeat_index=0,
        system_id="NATIVE",
        system_revision="native-revision",
        workload_seal_sha256=_digest("workload"),
        arrival_realization_sha256=_digest("arrival"),
        expected_enqueue_sequence_sha256=_digest("enqueue"),
        model_revision="model-revision",
        tokenizer_revision="tokenizer-revision",
        sampling_parameters_sha256=_digest("sampling"),
        engine_configuration_sha256=_digest("engine"),
        generation_config_sha256=_digest("generation"),
        execution_order_index=0,
        engine_instance_id="engine-native-01",
        isolation_preflight={
            "new_process": True,
            "new_engine": True,
            "cross_run_apc_reuse": False,
            "empty_cache_verified": True,
        },
        preheat_mode="NONE",
        runner_version="runner-v1",
        evaluator_version="evaluator-v1",
    )


def _result(run_input=None):
    return build_run_result_manifest(
        run_input_manifest=run_input or _input(),
        status="PASS",
        actual_enqueue_sequence_sha256=_digest("actual-enqueue"),
        evidence_sha256={
            "planned_events": _digest("planned"),
            "native_events": _digest("native"),
            "terminal_events": _digest("terminal"),
            "exposure_events": _digest("exposure"),
        },
        derived_metrics_sha256=_digest("metrics"),
        started_at="2026-11-18T00:00:00+08:00",
        ended_at="2026-11-18T00:01:00+08:00",
        failure_reason=None,
    )


def test_candidate_protocol_cannot_materialize_run_input() -> None:
    with pytest.raises(Phase5ProtocolValidationError, match="not authorized"):
        _input(_candidate_bundle())


def test_run_input_binds_protocol_contract_workload_and_runtime() -> None:
    bundle = _ready_bundle()
    manifest = _input(bundle)
    validate_run_input_manifest(manifest, bundle=bundle)
    assert manifest["contract_sha256"] == {
        name: digest for name, digest in bundle.sha256.items() if name != "protocol"
    }
    assert manifest["execution_authorized"] is True


def test_run_input_fails_closed_on_contract_hash_change() -> None:
    bundle = _ready_bundle()
    manifest = _input(bundle)
    manifest["contract_sha256"]["metrics"] = "0" * 64
    with pytest.raises(Phase5ManifestError, match="contract hashes"):
        validate_run_input_manifest(manifest, bundle=bundle)


def test_result_binds_input_without_archive_hash() -> None:
    run_input = _input()
    result = _result(run_input)
    validate_run_result_manifest(result, run_input_manifest=run_input)
    assert result["run_input_manifest_sha256"] == manifest_sha256(run_input)
    assert "archive_sha256" not in result


def test_non_pass_result_requires_failure_reason() -> None:
    with pytest.raises(Phase5ManifestError, match="failure reason"):
        build_run_result_manifest(
            run_input_manifest=_input(),
            status="FAIL_CLOSED",
            actual_enqueue_sequence_sha256=None,
            evidence_sha256={
                "planned_events": _digest("planned"),
                "native_events": _digest("native"),
                "terminal_events": _digest("terminal"),
                "exposure_events": _digest("exposure"),
            },
            derived_metrics_sha256=None,
            started_at="start",
            ended_at="end",
            failure_reason=None,
        )


def test_result_rejects_archive_hash_field_to_prevent_cycle() -> None:
    run_input = _input()
    result = _result(run_input)
    result["archive_sha256"] = _digest("archive")
    with pytest.raises(Phase5ManifestError, match="external envelope"):
        validate_run_result_manifest(result, run_input_manifest=run_input)


def test_external_archive_envelope_binds_result_and_archive() -> None:
    result = _result()
    envelope = build_archive_envelope(
        run_result_manifest=result,
        archive_sha256=_digest("archive bytes"),
        archive_format="tar.gz",
        archive_member_manifest_sha256=_digest("member manifest"),
    )
    validate_archive_envelope(envelope, run_result_manifest=result)
    assert envelope["run_result_manifest_sha256"] == manifest_sha256(result)
    assert envelope["envelope_is_external_to_archive"] is True


def test_archive_envelope_fails_on_result_mutation() -> None:
    result = _result()
    envelope = build_archive_envelope(
        run_result_manifest=result,
        archive_sha256=_digest("archive bytes"),
        archive_format="tar.gz",
        archive_member_manifest_sha256=_digest("member manifest"),
    )
    result["ended_at"] = "changed"
    with pytest.raises(Phase5ManifestError, match="result manifest hash"):
        validate_archive_envelope(envelope, run_result_manifest=result)


def test_canonical_serialization_is_order_independent_and_rejects_nan() -> None:
    assert canonical_bytes({"b": 2, "a": 1}) == canonical_bytes({"a": 1, "b": 2})
    with pytest.raises(ValueError, match="Out of range float"):
        canonical_bytes({"invalid": float("nan")})
