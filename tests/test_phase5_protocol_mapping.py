from __future__ import annotations

import pytest

from kvopt.workload.phase5_protocol_mapping import (
    MappingStatus,
    ProtocolFieldMapping,
    validate_protocol_implementation_mapping,
)


def _implemented(field: str) -> ProtocolFieldMapping:
    return ProtocolFieldMapping(
        protocol_field=field,
        implementation_references=("module:function",),
        evidence_references=("schema.field",),
        evaluator_references=("evaluator:function",),
        test_references=("tests/test_mapping.py::test_field",),
        status=MappingStatus.IMPLEMENTED,
    )


def test_mapping_requires_exact_protocol_field_coverage() -> None:
    report = validate_protocol_implementation_mapping(
        protocol_sha256="a" * 64,
        required_fields=("arms", "metric"),
        mappings=(_implemented("arms"), _implemented("metric")),
    )
    assert report["status"] == "PASS"
    assert report["blocked_fields"] == []
    assert len(report["mapping_sha256"]) == 64

    with pytest.raises(ValueError, match="coverage is not exact"):
        validate_protocol_implementation_mapping(
            protocol_sha256="a" * 64,
            required_fields=("arms", "metric"),
            mappings=(_implemented("arms"),),
        )


def test_blocked_mapping_is_explicit_and_cannot_pass() -> None:
    blocked = ProtocolFieldMapping(
        protocol_field="metric",
        implementation_references=(),
        evidence_references=(),
        evaluator_references=(),
        test_references=(),
        status=MappingStatus.BLOCKED_REQUIRES_M4,
        blocker="No observable Native fact is defined",
    )
    report = validate_protocol_implementation_mapping(
        protocol_sha256="b" * 64,
        required_fields=("metric",),
        mappings=(blocked,),
    )
    assert report["status"] == "BLOCKED_REQUIRES_M4"
    assert report["blocked_fields"] == ["metric"]


def test_implemented_mapping_requires_implementation_evidence_evaluator_and_test() -> None:
    with pytest.raises(ValueError, match="all four"):
        ProtocolFieldMapping(
            protocol_field="metric",
            implementation_references=("module:function",),
            evidence_references=(),
            evaluator_references=("evaluator:function",),
            test_references=("test",),
            status=MappingStatus.IMPLEMENTED,
        )
