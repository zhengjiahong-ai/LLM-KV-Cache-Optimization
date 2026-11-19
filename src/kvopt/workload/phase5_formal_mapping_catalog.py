"""Concrete implementation map for the merged Phase 5 Formal Protocol."""

from __future__ import annotations

from .phase5_protocol_mapping import (
    MappingStatus,
    ProtocolFieldMapping,
    validate_protocol_implementation_mapping,
)

FORMAL_PROTOCOL_FIELDS = (
    "protocol_identity_and_contracts",
    "workload_acquisition",
    "workload_qualification_and_seal",
    "replay_and_arrival",
    "six_system_execution",
    "candidate_evaluation",
    "native_evidence",
    "metrics_evaluation",
    "calibration_and_sample_size",
    "formal_freeze",
    "group_level_analysis",
    "campaign_archive",
    "gpu_conformance",
)


def _implemented(
    field: str,
    implementation: tuple[str, ...],
    evidence: tuple[str, ...],
    evaluator: tuple[str, ...],
    tests: tuple[str, ...],
) -> ProtocolFieldMapping:
    return ProtocolFieldMapping(
        protocol_field=field,
        implementation_references=implementation,
        evidence_references=evidence,
        evaluator_references=evaluator,
        test_references=tests,
        status=MappingStatus.IMPLEMENTED,
    )


def _blocked(
    field: str,
    *,
    blocker: str,
    implementation: tuple[str, ...] = (),
    evidence: tuple[str, ...] = (),
    evaluator: tuple[str, ...] = (),
    tests: tuple[str, ...] = (),
) -> ProtocolFieldMapping:
    return ProtocolFieldMapping(
        protocol_field=field,
        implementation_references=implementation,
        evidence_references=evidence,
        evaluator_references=evaluator,
        test_references=tests,
        status=MappingStatus.BLOCKED_REQUIRES_M4,
        blocker=blocker,
    )


def build_formal_protocol_implementation_mapping(
    protocol_sha256: str,
) -> dict[str, object]:
    """Build the review map without closing protocol-owned or GPU-only gates."""

    mappings = (
        _implemented(
            "protocol_identity_and_contracts",
            ("src/kvopt/workload/phase5_formal_protocol_validator.py",),
            ("configs/phase5/phase5-formal-protocol-v1.json",),
            ("src/kvopt/workload/phase5_formal_gate_ledger.py",),
            ("tests/test_phase5_formal_protocol_validator.py",),
        ),
        _blocked(
            "workload_acquisition",
            blocker=(
                "U4 BFCL acquisition is not authorized and no source-specific "
                "Formal Cohort has been acquired"
            ),
            implementation=("src/kvopt/workload/phase5_trace_contract.py",),
            evidence=("docs/experiments/phase5-workload-feasibility-report.md",),
            evaluator=("src/kvopt/workload/phase5_workload_qualification.py",),
            tests=("tests/test_phase5_trace_contract.py",),
        ),
        _implemented(
            "workload_qualification_and_seal",
            (
                "src/kvopt/workload/phase5_workload_qualification.py",
                "src/kvopt/workload/phase5_formal_seal.py",
            ),
            ("phase5.workload_qualification.v1", "phase5.formal_workload_seal.v1"),
            ("src/kvopt/workload/phase5_workload_qualification.py",),
            (
                "tests/test_phase5_workload_qualification.py",
                "tests/test_phase5_formal_seal.py",
            ),
        ),
        _implemented(
            "replay_and_arrival",
            ("src/kvopt/workload/phase5_replay.py",),
            ("phase5.n_session_replay_plan.v1",),
            ("src/kvopt/workload/phase5_native_async.py",),
            ("tests/test_phase5_replay.py",),
        ),
        _blocked(
            "six_system_execution",
            blocker=(
                "U1 DVA freeze, U2 Adapted scheduler scope and U3 Continuum "
                "Official compatibility remain unresolved"
            ),
            implementation=(
                "src/kvopt/workload/phase5_six_system_runner.py",
                "src/kvopt/workload/phase5_system_adapters.py",
                "src/kvopt/workload/phase5_formal_orchestrator.py",
            ),
            evidence=("phase5.formal_cpu_orchestration.v1",),
            evaluator=("src/kvopt/workload/phase5_formal_gate_ledger.py",),
            tests=(
                "tests/test_phase5_six_system_runner.py",
                "tests/test_phase5_system_adapters.py",
                "tests/test_phase5_formal_orchestrator.py",
            ),
        ),
        _implemented(
            "candidate_evaluation",
            (
                "src/kvopt/workload/phase5_candidate_evaluation.py",
                "src/kvopt/workload/phase5_dva_candidate_adapter.py",
                "src/kvopt/costaware/dva_er.py",
            ),
            (
                "docs/experiments/dva-er-v1-cpu-gate.json",
                "phase5.candidate_family_evaluation.v1",
            ),
            ("src/kvopt/profiling/phase5_candidate_physical_evidence.py",),
            (
                "tests/test_dva_er.py",
                "tests/test_phase5_dva_candidate_adapter.py",
                "tests/test_phase5_candidate_physical_evidence.py",
            ),
        ),
        _blocked(
            "native_evidence",
            blocker="live six-system EngineCore evidence has not been collected",
            implementation=(
                "src/kvopt/workload/phase5_asyncllm_adapter.py",
                "src/kvopt/profiling/phase5_formal_metrics.py",
            ),
            evidence=("phase5.formal_run_metrics.v1",),
            evaluator=("src/kvopt/profiling/phase5_candidate_exposure.py",),
            tests=(
                "tests/test_phase5_asyncllm_adapter.py",
                "tests/test_phase5_formal_metrics.py",
            ),
        ),
        _implemented(
            "metrics_evaluation",
            ("src/kvopt/profiling/phase5_formal_metrics.py",),
            ("phase5.formal_run_metrics.v1",),
            ("src/kvopt/profiling/phase5_formal_metrics.py",),
            ("tests/test_phase5_formal_metrics.py",),
        ),
        _blocked(
            "calibration_and_sample_size",
            blocker=(
                "M4 must resolve the stratum-fixed-effect versus pooled-df=7 "
                "numerical mapping; z approximation is prohibited"
            ),
            implementation=("src/kvopt/workload/phase5_calibration.py",),
            evidence=("phase5.calibration_analysis.v2",),
            evaluator=("src/kvopt/workload/phase5_calibration.py",),
            tests=("tests/test_phase5_calibration.py",),
        ),
        _implemented(
            "formal_freeze",
            ("src/kvopt/workload/phase5_formal_freeze.py",),
            ("phase5.formal_freeze_candidate.v1",),
            ("src/kvopt/workload/phase5_formal_freeze.py",),
            ("tests/test_phase5_formal_freeze.py",),
        ),
        _implemented(
            "group_level_analysis",
            ("src/kvopt/profiling/phase5_formal_analysis.py",),
            ("phase5.formal_group_analysis.v1",),
            ("src/kvopt/profiling/phase5_formal_analysis.py",),
            ("tests/test_phase5_formal_analysis.py",),
        ),
        _implemented(
            "campaign_archive",
            (
                "src/kvopt/workload/phase5_formal_manifests.py",
                "src/kvopt/workload/phase5_formal_archive.py",
            ),
            ("phase5.formal_campaign_archive_envelope.v1",),
            ("src/kvopt/workload/phase5_archive.py",),
            (
                "tests/test_phase5_formal_manifests.py",
                "tests/test_phase5_formal_archive.py",
            ),
        ),
        _blocked(
            "gpu_conformance",
            blocker=(
                "P5E Part A final changed-HEAD Seal and authorized GPU execution "
                "are absent; Part B Abort remains NOT_READY"
            ),
            implementation=(
                "src/kvopt/workload/phase5e_part_a.py",
                "src/kvopt/workload/phase5e_mock_runner.py",
            ),
            evidence=("phase5e.part_a_mock_pipeline_result.v1",),
            evaluator=("src/kvopt/workload/phase5_gpu_conformance.py",),
            tests=(
                "tests/test_phase5e_part_a.py",
                "tests/test_phase5e_mock_runner.py",
            ),
        ),
    )
    return validate_protocol_implementation_mapping(
        protocol_sha256=protocol_sha256,
        required_fields=FORMAL_PROTOCOL_FIELDS,
        mappings=mappings,
    )
