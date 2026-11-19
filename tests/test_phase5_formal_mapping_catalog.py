from __future__ import annotations

import hashlib
from pathlib import Path

from kvopt.workload.phase5_formal_mapping_catalog import (
    FORMAL_PROTOCOL_FIELDS,
    build_formal_protocol_implementation_mapping,
)


def test_concrete_protocol_mapping_reports_exact_open_gates() -> None:
    path = Path("configs/phase5/phase5-formal-protocol-v1.json")
    report = build_formal_protocol_implementation_mapping(
        hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert report["status"] == "BLOCKED_REQUIRES_M4"
    assert report["field_count"] == len(FORMAL_PROTOCOL_FIELDS)
    assert report["blocked_fields"] == [
        "workload_acquisition",
        "six_system_execution",
        "native_evidence",
        "gpu_conformance",
    ]
    assert len(report["mapping_sha256"]) == 64


def test_dva_mapping_binds_real_implementation_and_cpu_gate() -> None:
    path = Path("configs/phase5/phase5-formal-protocol-v1.json")
    report = build_formal_protocol_implementation_mapping(
        hashlib.sha256(path.read_bytes()).hexdigest()
    )
    rows = {row["protocol_field"]: row for row in report["mappings"]}
    dva = rows["candidate_evaluation"]
    assert "src/kvopt/costaware/dva_er.py" in dva["implementation_references"]
    assert "docs/experiments/dva-er-v1-cpu-gate.json" in dva["evidence_references"]
    calibration = rows["calibration_and_sample_size"]
    assert calibration["status"] == "IMPLEMENTED"
    assert (
        "src/kvopt/workload/phase5_calibration_backend.py"
        in calibration["implementation_references"]
    )
    assert rows["gpu_conformance"]["status"] == "BLOCKED_REQUIRES_M4"
