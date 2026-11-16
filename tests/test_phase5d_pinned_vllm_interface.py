from __future__ import annotations

import pytest

pytest.importorskip("vllm")

from scripts.spikes.audit_phase5d_vllm_identity import build_report


def test_pinned_vllm_randomized_request_identity_interface() -> None:
    report = build_report()
    assert report["status"] == "PASS"
    assert report["vllm_version"] == "0.27.1"
    assert report["request_id_randomization_enabled"] is True
    assert report["internal_differs_from_external"] is True
    assert report["external_identity_preserved"] is True
    assert report["collector_internal_identity_match"] is True
    assert report["request_state_query_source"] in {
        "HAS_REQUEST_METHOD",
        "REQUEST_STATES_MAPPING",
    }
    assert report["engine_created"] is False
    assert report["gpu_execution"] is False
