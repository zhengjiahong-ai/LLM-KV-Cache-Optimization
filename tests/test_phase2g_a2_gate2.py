import json
from pathlib import Path

import pytest

from kvopt.profiling.phase2g_a2_gate2 import (
    _selection_evidence,
    _strict_physical_evidence,
    _summary,
    _validate_execution_authorization,
    _validate_run_binding,
    aggregate_scenarios,
    compare_pair,
    evaluate_campaign,
)


def _run_summary(policy: str, *, recomputed: int) -> dict[str, object]:
    request = {
        "program_id": "agent-a",
        "prompt_tokens": 128,
        "eligible_prefix_tokens": 96,
        "cached_prefix_tokens": 96 - recomputed,
        "actual_prefill_tokens": 32 + recomputed,
        "recomputed_tokens": recomputed,
        "new_suffix_tokens": 32,
    }
    return {
        "status": "VALID",
        "scenario_id": "f1-draw-01",
        "family": "F1",
        "policy": policy,
        "repeat": 1,
        "git_sha": "abc123",
        "trace_sha256": "trace",
        "request_ids": ["agent-a:1", "agent-a:2"],
        "materialized_token_digests": {"agent-a:1": "x", "agent-a:2": "y"},
        "pairing_config": {"model": "model", "seed": 1},
        "pressure_release_mechanism_realized": True,
        "selection_mechanism_realized": policy == "A2",
        "selection_diverged": True if policy == "A2" else None,
        "physical_eviction_count": 1,
        "physical_eviction_signature": [("agent-a", recomputed)],
        "strict_physical_eviction_signature": [(f"content-{recomputed}", "process-a")],
        "unmapped_physical_eviction_count": 0,
        "physical_evidence_observable": True,
        "aggregate_recomputed_tokens": recomputed,
        "aggregate_actual_prefill_tokens": 32 + recomputed,
        "aggregate_new_suffix_tokens": 32,
        "request_outcomes": {"agent-a:2": request},
    }


def test_pair_reports_native_benefit_using_frozen_recomputation_metric() -> None:
    row = compare_pair(_run_summary("A0", recomputed=32), _run_summary("A2", recomputed=16))

    assert row["status"] == "COMPARABLE"
    assert row["evidence_state"] == "NATIVE_BENEFIT_OBSERVED"
    assert row["delta_recomputed_tokens_a2_minus_a0"] == -16
    assert row["delta_actual_prefill_tokens_a2_minus_a0"] == -16
    assert row["delta_new_suffix_tokens_a2_minus_a0"] == 0
    assert row["metric_equivalence"] == "EXACT"


def test_pair_fails_closed_when_selection_identity_is_not_observable() -> None:
    a0 = _run_summary("A0", recomputed=32)
    a2 = _run_summary("A2", recomputed=16)
    a2["selection_diverged"] = None

    row = compare_pair(a0, a2)

    assert row["evidence_state"] == "SELECTION_NOT_OBSERVABLE"
    assert row["selection_diverged"] is None


def test_scenario_is_inconclusive_without_two_comparable_repeats() -> None:
    pairs = [
        {
            "scenario_id": "f1-draw-01",
            "family": "F1",
            "status": "COMPARABLE",
            "evidence_state": "NATIVE_BENEFIT_OBSERVED",
            "selection_diverged": True,
            "physical_diverged": True,
            "delta_recomputed_tokens_a2_minus_a0": -16,
        },
        {
            "scenario_id": "f1-draw-01",
            "family": "F1",
            "status": "NOT_COMPARABLE",
            "evidence_state": "INCONCLUSIVE",
            "selection_diverged": None,
            "physical_diverged": None,
            "delta_recomputed_tokens_a2_minus_a0": None,
        },
    ]

    row = aggregate_scenarios(pairs)[0]

    assert row["comparable_repeat_count"] == 1
    assert row["mean_delta_recomputed_tokens_a2_minus_a0"] is None
    assert row["direction"] == "INCONCLUSIVE"


def test_campaign_missingness_blocks_formal_summary_but_keeps_descriptive_stats() -> None:
    rows = [
        {
            "direction": "BETTER",
            "selection_diverged": True,
            "physical_diverged": True,
            "mean_delta_recomputed_tokens_a2_minus_a0": -16,
        }
        for _ in range(35)
    ]

    summary = _summary(rows, required_complete_scenarios=36)

    assert summary["formal_verdict"] == "INCONCLUSIVE"
    assert summary["formal_mean_delta_recomputed_tokens_a2_minus_a0"] is None
    assert (
        summary["descriptive_complete_scenarios_only"][
            "mean_delta_recomputed_tokens_a2_minus_a0"
        ]
        == -16
    )


def test_evaluator_refuses_execution_locked_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"execution_authorized": False, "runs": [], "scenarios": []}),
        encoding="utf-8",
    )

    authorization = tmp_path / "authorization.json"
    authorization.write_text(
        json.dumps(
            {
                "schema_version": "phase2g.a2_gate2_authorization.v1",
                "formal_native_execution_authorized": False,
                "execution_authorized": False,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not authorized"):
        evaluate_campaign(
            manifest_path=manifest,
            authorization_path=authorization,
            run_root=tmp_path,
        )


def _physical_events() -> list[dict[str, object]]:
    return [
        {
            "event_index": 1,
            "event_type": "VLLM_PREFIX_SNAPSHOT",
            "payload": {
                "block_ids": [7],
                "ordered_native_cache_keys": ["content-a"],
                "native_hash_process_id": "process-a",
            },
        },
        {"event_index": 2, "event_type": "FORCED_RELEASE_DECISION", "payload": {}},
        {"event_index": 3, "event_type": "COST_AWARE_BLOCK_DECISION", "payload": {}},
        {
            "event_index": 4,
            "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
            "payload": {
                "block_id": 7,
                "native_cache_key_before": "content-a",
                "native_hash_process_id": "process-a",
                "hash_removed_after": True,
            },
        },
    ]


@pytest.mark.parametrize("case", ["process", "removal", "order", "reuse", "unmapped"])
def test_physical_evidence_fails_closed_on_incomplete_identity_chain(case: str) -> None:
    events = _physical_events()
    eviction = events[-1]
    if case == "process":
        eviction["payload"]["native_hash_process_id"] = "process-b"
    elif case == "removal":
        eviction["payload"]["hash_removed_after"] = False
    elif case == "order":
        eviction["event_index"] = 2
        events[1]["event_index"] = 3
        events[2]["event_index"] = 4
    elif case == "reuse":
        events.insert(
            3,
            {
                "event_index": 4,
                "event_type": "VLLM_PREFIX_SNAPSHOT",
                "payload": {
                    "block_ids": [7],
                    "ordered_native_cache_keys": ["content-b"],
                    "native_hash_process_id": "process-a",
                },
            },
        )
        eviction["event_index"] = 5
    else:
        events.append(
            {
                "event_index": 5,
                "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
                "payload": {
                    "block_id": 8,
                    "native_cache_key_before": "content-b",
                    "native_hash_process_id": "process-a",
                    "hash_removed_after": True,
                },
            }
        )

    evidence = _strict_physical_evidence(events, require_block_decision=True)

    assert evidence["physical_evidence_observable"] is False
    assert evidence["physical_evidence_problems"]


def _selection_events(payload_updates: dict[str, object]) -> list[dict[str, object]]:
    payload = {
        "required_blocks": 1,
        "legal_block_ids": [7, 8],
        "selected_victims": [7],
        "native_lru_victims": [8],
        "legal_content_hashes": [
            {"block_id": 7, "content_hash": "content-a"},
            {"block_id": 8, "content_hash": "content-b"},
        ],
        "native_hash_process_id": "process-a",
        "selector": "incremental_greedy",
        "fallbacks": [],
        "adapter_problems": [],
        "contract_problems": [],
    }
    payload.update(payload_updates)
    return [
        {"event_index": 1, "event_type": "FORCED_RELEASE_DECISION", "payload": {}},
        {"event_index": 2, "event_type": "COST_AWARE_BLOCK_DECISION", "payload": payload},
    ]


@pytest.mark.parametrize(
    "updates",
    [
        {"selected_victims": [9]},
        {"required_blocks": 2},
        {"legal_content_hashes": [{"block_id": 7, "content_hash": "content-a"}]},
        {"adapter_problems": ["stale snapshot"]},
        {"contract_problems": ["invalid candidate"]},
        {"fallbacks": ["missing identity"], "selector": "incremental_greedy"},
    ],
)
def test_selection_contract_rejects_invalid_or_incomplete_decisions(
    updates: dict[str, object],
) -> None:
    evidence = _selection_evidence(_selection_events(updates))

    assert evidence["selection_contract_valid"] is False
    assert evidence["selection_mechanism_realized"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("campaign_manifest_sha256", "wrong", "frozen manifest"),
        ("tested_a2_implementation_git_sha", "wrong", "implementation SHA"),
        ("experiment_tooling_git_sha", "short", "tooling SHA"),
        ("authorized_config_sha256", {"run-1": "wrong"}, "config hashes"),
        ("authorized_trace_sha256", {"scenario-1": "wrong"}, "trace hashes"),
    ],
)
def test_execution_authorization_rejects_binding_tampering(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    import hashlib

    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "tested_a2_implementation_git_sha": "a2" * 20,
        "runs": [
            {
                "run_id": "run-1",
                "config_sha256": "config-sha",
            }
        ],
        "scenarios": [
            {
                "scenario_id": "scenario-1",
                "trace_sha256": "trace-sha",
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    authorization = {
        "schema_version": "phase2g.a2_gate2_authorization.v1",
        "formal_native_execution_authorized": True,
        "execution_authorized": True,
        "campaign_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "tested_a2_implementation_git_sha": "a2" * 20,
        "experiment_tooling_git_sha": "b1" * 20,
        "authorized_config_sha256": {"run-1": "config-sha"},
        "authorized_trace_sha256": {"scenario-1": "trace-sha"},
    }
    authorization[field] = value
    authorization_path = tmp_path / "authorization.json"
    authorization_path.write_text(json.dumps(authorization), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        _validate_execution_authorization(
            manifest_path=manifest_path,
            authorization_path=authorization_path,
        )


@pytest.mark.parametrize("case", ["config", "trace", "tooling"])
def test_actual_run_binding_rejects_frozen_evidence_drift(
    tmp_path: Path, case: str
) -> None:
    import hashlib

    config = tmp_path / "config.json"
    trace = tmp_path / "trace.json"
    config.write_text('{"config": 1}\n', encoding="utf-8")
    trace.write_text('{"trace": 1}\n', encoding="utf-8")
    config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    trace_sha = hashlib.sha256(trace.read_bytes()).hexdigest()
    run_manifest = {
        "config_sha256": config_sha,
        "trace_sha256": trace_sha,
        "git_sha": "b1" * 20,
    }
    (tmp_path / "run.json").write_text(json.dumps(run_manifest), encoding="utf-8")
    entry = {"config_sha256": config_sha, "trace_sha256": trace_sha}
    authorization = {"experiment_tooling_git_sha": "b1" * 20}
    if case == "config":
        config.write_text('{"config": 2}\n', encoding="utf-8")
    elif case == "trace":
        trace.write_text('{"trace": 2}\n', encoding="utf-8")
    else:
        run_manifest["git_sha"] = "c2" * 20
        (tmp_path / "run.json").write_text(json.dumps(run_manifest), encoding="utf-8")

    with pytest.raises(ValueError):
        _validate_run_binding(tmp_path, entry, authorization)
