"""Validate the frozen W1-B long-context PrefillReload measurement protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

W1B_TOKEN_GRID = (256, 1024, 2048, 3072, 4096, 5120)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def validate_protocol(*, protocol_path: Path, audit_path: Path) -> dict[str, Any]:
    protocol = _load(protocol_path)
    audit = _load(audit_path)
    if protocol.get("schema_version") != "continuum.w1b_prefill_profile_protocol.v1":
        raise ValueError("unsupported W1-B profile protocol")
    if protocol.get("token_grid") != list(W1B_TOKEN_GRID):
        raise ValueError("W1-B long-context token grid changed")
    if protocol.get("legacy_phase1b_profile_modified") is not False:
        raise ValueError("W1-B must not modify the frozen Phase 1B profile")
    if protocol.get("formal_performance_campaign_authorized") is not False:
        raise ValueError("W1-B profile measurement is not a formal performance campaign")
    measurement = protocol.get("measurement")
    if not isinstance(measurement, dict) or measurement.get(
        "warmup_pairs_per_point"
    ) != 5 or measurement.get("measured_pairs_per_point") != 20:
        raise ValueError("W1-B profile must preserve the 5/20 pair protocol")
    if measurement.get("raw_delta_definition") != "MISS - HIT TTFT":
        raise ValueError("W1-B profile changed the PrefillReload definition")
    requirement = protocol.get("coverage_requirement")
    if not isinstance(requirement, dict) or requirement.get("extrapolation") != "PROHIBITED":
        raise ValueError("W1-B profile must prohibit extrapolation")
    minimum = int(audit["minimum_query_tokens"])
    maximum = int(audit["maximum_query_tokens"])
    if minimum < W1B_TOKEN_GRID[0] or maximum > W1B_TOKEN_GRID[-1]:
        raise ValueError("W1-B measured grid does not cover frozen replay queries")
    if requirement.get("minimum_query_tokens") != minimum or requirement.get(
        "maximum_query_tokens"
    ) != maximum:
        raise ValueError("W1-B protocol coverage does not match the frozen audit")
    return {
        "schema_version": "continuum.w1b_prefill_profile_protocol_validation.v1",
        "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "coverage_audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        "token_grid": list(W1B_TOKEN_GRID),
        "frozen_query_range": [minimum, maximum],
        "pair_count": len(W1B_TOKEN_GRID) * 25,
        "legacy_profile_unchanged": True,
        "verdict": "PASS_READY_FOR_BOUNDED_MEASUREMENT",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate_protocol(protocol_path=args.protocol, audit_path=args.audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"W1-B profile protocol: {report['verdict']} -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
