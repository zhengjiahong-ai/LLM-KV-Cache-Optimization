from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_dva_native_provider import (
    DVAERNativeDecisionProvider,
    DVAERNativeProviderError,
    production_provider_status,
)


def _state():
    candidates = {
        "engine_core_identity": "core-1",
        "source": "LIVE_RETENTION_MANAGER",
        "observed_at_timestamp": 9.0,
        "legal_candidate_ids": ["a", "b"],
        "candidate_key_by_id": {"a": ["p-a", "prefix-a"], "b": ["p-b", "prefix-b"]},
        "a0_order": ["a", "b"],
        "a0_baseline_selection": "a",
        "a1_features": {"scores": {"a": 1, "b": 2}},
        "a3_features": {"scores": {"a": 2, "b": 1}},
    }
    pool = {
        "engine_core_identity": "core-1",
        "source": "LIVE_VLLM_BLOCK_POOL",
        "observed_at_timestamp": 9.0,
        "free_queue_order": [10, 11],
        "blocks": [
            {
                "block_id": 10,
                "has_hash": True,
                "refcount": 0,
                "native_lru_rank": 0,
                "owner_candidate_ids": ["a"],
                "protected_candidate_ids": ["a"],
            },
            {
                "block_id": 11,
                "has_hash": True,
                "refcount": 0,
                "native_lru_rank": 1,
                "owner_candidate_ids": ["b"],
                "protected_candidate_ids": ["b"],
            },
        ],
    }
    timers = {
        "engine_core_identity": "core-1",
        "source": "CONTROLLER_ARMED_TIMER",
        "observed_at_timestamp": 9.0,
        "followups": {
            candidate_id: {
                "chain_id": f"chain-{candidate_id}",
                "active": True,
                "pending_tool_gap_seconds": 2.0,
                "armed_at_timestamp": 8.0,
                "observed_at_timestamp": 9.0,
                "expires_at_timestamp": 12.0,
                "pending_tool_gap_source": "CONTROLLER_ARMED_TIMER",
            }
            for candidate_id in ("a", "b")
        },
    }
    return pool, candidates, timers


def _provider(pool, candidates, timers):
    return DVAERNativeDecisionProvider(
        engine_core_identity="core-1",
        block_pool_reader=lambda: pool,
        candidate_reader=lambda: candidates,
        timer_reader=lambda: timers,
    )


def _build(provider):
    return provider.build_snapshot(
        decision_id="d1",
        group_id="g1",
        stratum="SWE_BENCH",
        program_id="p",
        session_id="s",
        turn_id="t",
        trace_sha256="1" * 64,
        decision_timestamp=10.0,
        required_blocks=1,
        h_seconds=60.0,
    )


def test_live_provider_binds_pool_owner_protection_and_timer() -> None:
    pool, candidates, timers = _state()
    snapshot = _build(_provider(pool, candidates, timers))
    assert snapshot.evidence_coverage["same_engine_core"] is True
    assert snapshot.candidate_features_by_algorithm["DVA_ER_V1"]["blocks"][0]["refcount"] == 0


@pytest.mark.parametrize(
    "mutation", ["future_timer", "expired_timer", "missing_owner", "wrong_core"]
)
def test_live_provider_fails_closed_on_invalid_runtime_evidence(mutation: str) -> None:
    pool, candidates, timers = deepcopy(_state())
    if mutation == "future_timer":
        timers["followups"]["a"]["observed_at_timestamp"] = 11.0
    elif mutation == "expired_timer":
        timers["followups"]["a"]["expires_at_timestamp"] = 9.0
    elif mutation == "missing_owner":
        del pool["blocks"][0]["owner_candidate_ids"]
    else:
        pool["engine_core_identity"] = "other"
    with pytest.raises(DVAERNativeProviderError):
        _build(_provider(pool, candidates, timers))


def test_provider_status_does_not_turn_cpu_fixture_into_native_pass() -> None:
    assert production_provider_status(object()) == {
        "schema_version": "phase5.dva_er_native_provider_status.v1",
        "status": "NOT_INSTALLED",
        "cpu_fixture_status": "PASS",
        "native_runtime_conformance": "NOT_RUN",
        "missing_interface": "dva_er_native_decision_provider",
    }
