from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.continuum_w1b_profile import validate_protocol


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _protocol() -> dict[str, object]:
    return {
        "schema_version": "continuum.w1b_prefill_profile_protocol.v1",
        "token_grid": [256, 1024, 2048, 3072, 4096, 5120],
        "legacy_phase1b_profile_modified": False,
        "formal_performance_campaign_authorized": False,
        "measurement": {
            "warmup_pairs_per_point": 5,
            "measured_pairs_per_point": 20,
            "raw_delta_definition": "MISS - HIT TTFT",
        },
        "coverage_requirement": {
            "minimum_query_tokens": 1456,
            "maximum_query_tokens": 5088,
            "extrapolation": "PROHIBITED",
        },
    }


def test_protocol_covers_frozen_queries_without_extrapolation(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.json"
    audit = tmp_path / "audit.json"
    _write(protocol, _protocol())
    _write(audit, {"minimum_query_tokens": 1456, "maximum_query_tokens": 5088})
    result = validate_protocol(protocol_path=protocol, audit_path=audit)
    assert result["pair_count"] == 150
    assert result["verdict"] == "PASS_READY_FOR_BOUNDED_MEASUREMENT"


def test_protocol_rejects_range_requiring_extrapolation(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.json"
    audit = tmp_path / "audit.json"
    _write(protocol, _protocol())
    _write(audit, {"minimum_query_tokens": 1456, "maximum_query_tokens": 6000})
    with pytest.raises(ValueError, match="does not cover"):
        validate_protocol(protocol_path=protocol, audit_path=audit)
