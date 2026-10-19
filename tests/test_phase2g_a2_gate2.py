import json
from pathlib import Path

import pytest

from kvopt.profiling.phase2g_a2_gate2 import (
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


def test_evaluator_refuses_execution_locked_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"execution_authorized": False, "runs": [], "scenarios": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="execution-locked"):
        evaluate_campaign(manifest_path=manifest, run_root=tmp_path)
