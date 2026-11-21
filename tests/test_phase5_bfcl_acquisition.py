from __future__ import annotations

import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_bfcl_acquisition import (
    BFCLAcquisitionError,
    build_bfcl_preflight_report,
    validate_bfcl_sampling_frame,
)

FRAME = Path("configs/phase5/phase5-bfcl-sampling-frame-v1.json")
BFCL_ROOT = Path("data/phase5-bfcl-gorilla")


def test_pinned_bfcl_source_and_200_case_frame() -> None:
    if not BFCL_ROOT.exists():
        return
    frame = json.loads(FRAME.read_text(encoding="utf-8"))
    source = BFCL_ROOT / frame["source"]["source_file"]
    report = validate_bfcl_sampling_frame(
        frame_path=FRAME,
        source_path=source,
        observed_revision=frame["source"]["revision"],
    )
    assert report["status"] == "PASS"
    assert report["formal_case_count"] == 200
    assert report["snippet_case_count"] == 100
    assert report["no_snippet_case_count"] == 100


def test_bfcl_source_revision_mismatch_fails_closed(tmp_path: Path) -> None:
    frame = json.loads(FRAME.read_text(encoding="utf-8"))
    source = tmp_path / "source.jsonl"
    source.write_bytes(
        (
            BFCL_ROOT / frame["source"]["source_file"]
        ).read_bytes()
        if BFCL_ROOT.exists()
        else b""
    )
    with pytest.raises(BFCLAcquisitionError, match="revision mismatch"):
        validate_bfcl_sampling_frame(
            frame_path=FRAME,
            source_path=source,
            observed_revision="0" * 40,
        )


def test_bfcl_preflight_separates_protocol_from_adapter_requirements() -> None:
    report = build_bfcl_preflight_report(
        source_validation={"status": "PASS", "validation_sha256": "a" * 64},
        protocol_sha256="b" * 64,
        qualification_contract_sha256="c" * 64,
        expected_model="Qwen/Qwen2.5-Coder-1.5B-Instruct",
        expected_model_revision="d" * 40,
        endpoint_models=["some-other-model"],
        model_endpoint_configured=True,
        acquisition_adapter="PINNED_BFCL_SERPAPI",
        adapter_runtime_ready=False,
    )
    assert report["status"] == "FAIL_CLOSED"
    assert report["blockers"] == [
        "EXPECTED_MODEL_SERVED",
        "ADAPTER_RUNTIME_READY",
    ]
    assert "SERPAPI_KEY_PRESENT" not in report["protocol_checks"]
    assert report["adapter_runtime_requirement_is_protocol_requirement"] is False
    assert report["credentials_recorded"] is False


def test_bfcl_preflight_ready_does_not_authorize_gpu_or_select_cohort() -> None:
    model = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
    report = build_bfcl_preflight_report(
        source_validation={"status": "PASS", "validation_sha256": "a" * 64},
        protocol_sha256="b" * 64,
        qualification_contract_sha256="c" * 64,
        expected_model=model,
        expected_model_revision="d" * 40,
        endpoint_models=[model],
        model_endpoint_configured=True,
        acquisition_adapter="PINNED_BFCL_SERPAPI",
        adapter_runtime_ready=True,
    )
    assert report["status"] == "READY"
    assert report["formal_cohort_selected"] is False
    assert report["gpu_execution_authorized"] is False
