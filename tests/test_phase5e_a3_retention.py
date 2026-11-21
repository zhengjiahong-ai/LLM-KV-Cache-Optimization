from __future__ import annotations

import copy

from kvopt.workload.phase5_replay import canonical_sha256
from kvopt.workload.phase5e_a3_retention import (
    PREFILL_MODEL,
    PREFILL_PROFILE_PATH,
    PREFILL_PROFILE_SHA256,
    PREFILL_PROTOCOL_REVISION,
    PREFILL_REVISION,
    execute_g9_bound_selection,
)


def _seal(payload: dict[str, object]) -> dict[str, object]:
    payload["manifest_sha256"] = canonical_sha256(payload)
    return payload


def _manifest() -> dict[str, object]:
    candidates = [f"p{index}:r1" for index in range(1, 5)]
    engine = "engine-core-1"
    boundary = "phase5e-pressure-01"
    timestamp = 2.001
    ttl_rows = []
    retention_rows = []
    chain_rows = []
    for index, prefix_id in enumerate(candidates, start=1):
        ttl_input = {
            "program_id": f"p{index}",
            "request_id": prefix_id,
            "prefix_id": prefix_id,
            "decision_timestamp": timestamp,
            "next_tool_type": None,
            "global_server_gap_samples_seconds": [],
            "tool_server_gap_samples_seconds": [],
            "queue_delay_t_seconds": 0.0,
            "eta": 1.0,
            "prefill_reload_seconds": 0.01,
            "default_ttl_seconds": 1.0,
        }
        ttl_decision = {
            "ttl_seconds": 1.0,
            "deadline_timestamp": timestamp + 1.0,
            "history_mode": "COLD_START",
            "reason": "insufficient global server gap history",
        }
        decision_sha = canonical_sha256(ttl_decision)
        blocks = [index * 10, index * 10 + 1]
        ttl_rows.append(
            {
                "program_id": f"p{index}",
                "request_id": prefix_id,
                "prefix_id": prefix_id,
                "engine_core_identity": engine,
                "decision_boundary_id": boundary,
                "ttl_input": ttl_input,
                "ttl_input_sha256": canonical_sha256(ttl_input),
                "ttl_decision": ttl_decision,
                "ttl_decision_sha256": decision_sha,
                "source_event_refs": [f"ttl-input:{prefix_id}"],
            }
        )
        retention_rows.append(
            {
                "program_id": f"p{index}",
                "prefix_id": prefix_id,
                "engine_core_identity": engine,
                "decision_boundary_id": boundary,
                "protected": True,
                "waiting_followup": False,
                "block_ids": blocks,
                "ttl_decision_sha256": decision_sha,
            }
        )
        chain_rows.append(
            {
                "prefix_id": prefix_id,
                "engine_core_identity": engine,
                "decision_boundary_id": boundary,
                "block_ids": blocks,
                "content_hashes": [
                    canonical_sha256([prefix_id, block_id]) for block_id in blocks
                ],
                "native_hash_process_id": "native-hash-process-1",
                "chain_depth_proof_sha256": canonical_sha256(
                    {"prefix_id": prefix_id, "blocks": blocks}
                ),
            }
        )
    payload: dict[str, object] = {
        "schema_version": "phase5e.a3_retention_input_manifest.v1",
        "run_id": "P5E-A-01",
        "decision_id": "decision-1",
        "decision_boundary": {
            "boundary_id": boundary,
            "timestamp": timestamp,
            "clock_domain": "continuum_lifecycle",
        },
        "engine_core_identity": {
            "identity": engine,
            "installation_report_sha256": "a" * 64,
        },
        "a3_candidate_ids": candidates,
        "ttl_inputs": ttl_rows,
        "retention_entries": retention_rows,
        "prefill": {
            "model": PREFILL_MODEL,
            "model_revision": PREFILL_REVISION,
            "tokenizer_revision": PREFILL_REVISION,
            "profile_path": PREFILL_PROFILE_PATH,
            "profile_sha256": PREFILL_PROFILE_SHA256,
            "protocol_revision": PREFILL_PROTOCOL_REVISION,
            "query_token_count": 1984,
            "estimate_seconds": 0.01,
            "provenance": "APPROXIMATED",
        },
        "histories": {
            "server_gap": {
                "samples": [],
                "provenance": "EXPLICIT_COLD_START",
                "reason": "NO_COMPLETED_TOOL_GAPS",
                "source_event_refs": [],
            },
            "queue_delay": {
                "value": 0.0,
                "provenance": "EXPLICIT_COLD_START",
                "reason": "NO_EVICTED_REQUEST_QUEUE_DELAY",
                "source_event_refs": [],
            },
            "eta": {
                "value": 1.0,
                "provenance": "APPROXIMATED",
                "reason": "FULLY_MEMORYFUL_COLD_START",
                "source_event_refs": [],
            },
        },
        "prefix_chain": chain_rows,
        "lifecycle": [
            {
                "event_type": "TURN_FINISHED",
                "event_index": index,
                "timestamp": 1.0 + index * 0.1,
                "clock_domain": "continuum_lifecycle",
                "source_event_sha256": canonical_sha256(["TURN_FINISHED", index]),
            }
            for index in range(4)
        ],
        "checks": {
            "required_inputs_complete": True,
            "same_engine_core": True,
            "same_decision_boundary": True,
            "temporal_order_valid": True,
            "no_future_information": True,
            "prefill_profile_hash_valid": True,
            "prefix_block_hash_depth_consistent": True,
            "cold_start_explicit": True,
        },
    }
    return _seal(payload)


def _assert_fail_closed(payload: dict[str, object]) -> None:
    calls = []
    report, result = execute_g9_bound_selection(payload, lambda: calls.append("A3"))
    assert report["status"] == "FAIL_CLOSED"
    assert report["a3_selection"] == "NOT_EXECUTED"
    assert report["native_lru_fallback"] == "FORBIDDEN"
    assert report["synthetic_values_inserted"] is False
    assert result is None
    assert calls == []


def test_g9_passes_complete_hash_bound_manifest_and_runs_a3_once() -> None:
    calls = []
    report, result = execute_g9_bound_selection(
        _manifest(), lambda: calls.append("A3") or "selected"
    )
    assert report["status"] == "PASS"
    assert result == "selected"
    assert calls == ["A3"]


def test_g9_fails_on_ttl_deadline_inconsistency() -> None:
    payload = _manifest()
    payload["ttl_inputs"][0]["ttl_decision"]["deadline_timestamp"] = 99.0
    _seal(payload)
    _assert_fail_closed(payload)


def test_g9_fails_on_wrong_prefill_profile() -> None:
    payload = _manifest()
    payload["prefill"]["profile_sha256"] = "b" * 64
    _seal(payload)
    _assert_fail_closed(payload)


def test_g9_fails_on_future_lifecycle_information() -> None:
    payload = _manifest()
    payload["lifecycle"][0]["timestamp"] = 3.0
    _seal(payload)
    _assert_fail_closed(payload)


def test_g9_fails_on_cross_engine_core_or_boundary() -> None:
    payload = _manifest()
    payload["retention_entries"][0]["engine_core_identity"] = "other-core"
    _seal(payload)
    _assert_fail_closed(payload)


def test_g9_fails_on_prefix_block_hash_depth_mismatch() -> None:
    payload = _manifest()
    payload["prefix_chain"][0]["block_ids"] = [999, 1000]
    _seal(payload)
    _assert_fail_closed(payload)


def test_g9_fails_on_missing_history_provenance() -> None:
    payload = copy.deepcopy(_manifest())
    payload["histories"]["server_gap"].pop("provenance")
    _seal(payload)
    _assert_fail_closed(payload)
