"""Research-semantic-neutral implementation mapping for an M4 protocol."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum

from .phase5_replay import canonical_sha256


class MappingStatus(StrEnum):
    IMPLEMENTED = "IMPLEMENTED"
    BLOCKED_REQUIRES_M4 = "BLOCKED_REQUIRES_M4"


@dataclass(frozen=True, slots=True)
class ProtocolFieldMapping:
    protocol_field: str
    implementation_references: tuple[str, ...]
    evidence_references: tuple[str, ...]
    evaluator_references: tuple[str, ...]
    test_references: tuple[str, ...]
    status: MappingStatus
    blocker: str | None = None

    def __post_init__(self) -> None:
        if not self.protocol_field:
            raise ValueError("protocol_field must be non-empty")
        collections = (
            self.implementation_references,
            self.evidence_references,
            self.evaluator_references,
            self.test_references,
        )
        if any(
            any(not isinstance(row, str) or not row for row in values)
            for values in collections
        ):
            raise ValueError("mapping references must be non-empty strings")
        if self.status is MappingStatus.IMPLEMENTED:
            if any(not values for values in collections):
                raise ValueError("implemented mapping requires all four reference types")
            if self.blocker is not None:
                raise ValueError("implemented mapping cannot retain a blocker")
        elif not self.blocker:
            raise ValueError("blocked mapping must state the M4-facing blocker")

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


def validate_protocol_implementation_mapping(
    *,
    protocol_sha256: str,
    required_fields: Sequence[str],
    mappings: Sequence[ProtocolFieldMapping],
) -> dict[str, object]:
    """Require exact field coverage without defining the research fields."""

    if len(protocol_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in protocol_sha256
    ):
        raise ValueError("protocol_sha256 must be a lowercase SHA-256 digest")
    if not required_fields or len(required_fields) != len(set(required_fields)):
        raise ValueError("required protocol fields must be non-empty and unique")
    by_field = {row.protocol_field: row for row in mappings}
    if len(by_field) != len(mappings):
        raise ValueError("protocol mapping contains duplicate fields")
    if set(by_field) != set(required_fields):
        raise ValueError("protocol mapping field coverage is not exact")
    blocked = [
        field
        for field in required_fields
        if by_field[field].status is MappingStatus.BLOCKED_REQUIRES_M4
    ]
    payload = {
        "schema_version": "phase5.protocol_implementation_mapping.v1",
        "protocol_sha256": protocol_sha256,
        "status": "PASS" if not blocked else "BLOCKED_REQUIRES_M4",
        "field_count": len(required_fields),
        "blocked_fields": blocked,
        "mappings": [by_field[field].to_dict() for field in required_fields],
    }
    return {**payload, "mapping_sha256": canonical_sha256(payload)}


def mapping_from_record(record: Mapping[str, object]) -> ProtocolFieldMapping:
    """Parse a persisted record after the M4 protocol supplies field names."""

    return ProtocolFieldMapping(
        protocol_field=str(record.get("protocol_field", "")),
        implementation_references=tuple(record.get("implementation_references", ())),
        evidence_references=tuple(record.get("evidence_references", ())),
        evaluator_references=tuple(record.get("evaluator_references", ())),
        test_references=tuple(record.get("test_references", ())),
        status=MappingStatus(str(record.get("status", ""))),
        blocker=None if record.get("blocker") is None else str(record["blocker"]),
    )
