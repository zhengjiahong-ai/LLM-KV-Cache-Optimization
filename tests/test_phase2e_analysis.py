import pytest

from kvopt.profiling.phase2e_analysis import compare_run_pair, compute_run_metrics


def _run(baseline: str, losses: tuple[int, int] = (0, 8)) -> dict[str, object]:
    rows = []
    for index, loss in enumerate(losses):
        rows.append(
            {
                "request_id": f"a:{index + 1}",
                "program_id": "a",
                "kind": "turn",
                "native_prompt_tokens": 16,
                "eligible_prefix_tokens": 8,
                "native_cached_prefix_tokens": 8 - loss,
                "native_queued_timestamp": float(index),
                "native_scheduler_admission_timestamp": float(index) + 0.1,
                "native_first_token_timestamp": float(index) + 0.3,
                "apc_outcome": "FULL_HIT" if loss == 0 else "MISS",
            }
        )
    return {
        "run_id": f"run-{baseline}",
        "scenario_id": "f1-draw-01",
        "family": "F1",
        "baseline": baseline,
        "repeat": 1,
        "status": "VALID",
        "family_mechanism_status": "REALIZED",
        "request_evidence": rows,
    }


def test_compute_run_metrics_uses_frozen_token_decomposition() -> None:
    result = compute_run_metrics(_run("native-lru"))

    assert result["status"] == "COMPUTABLE"
    assert result["metrics"]["A1.1_aggregate_recomputed_tokens"]["value"] == 8
    assert result["metrics"]["A1.1a_aggregate_actual_prefill_tokens"]["value"] == 24
    assert result["metrics"]["A1.1b_aggregate_new_suffix_tokens"]["value"] == 16
    assert result["metrics"]["A1.3_mean_ttft_seconds"]["value"] == pytest.approx(0.3)


def test_pair_delta_is_continuum_minus_native_lru() -> None:
    native = compute_run_metrics(_run("native-lru", (8, 8)))
    continuum = compute_run_metrics(_run("continuum-baseline", (0, 8)))

    result = compare_run_pair(native, continuum)

    assert result["status"] == "COMPARABLE"
    assert result["metrics"]["A1.7_aggregate_delta_tokens"]["value"] == -8
    assert result["metrics"]["A1.8_gross_request_level_change_tokens"]["value"] == 8
    assert result["metrics"]["A1.9_net_to_gross_ratio"]["value"] == 1


def test_pair_zero_gross_is_not_applicable() -> None:
    native = compute_run_metrics(_run("native-lru"))
    continuum = compute_run_metrics(_run("continuum-baseline"))

    result = compare_run_pair(native, continuum)

    assert result["metrics"]["A1.9_net_to_gross_ratio"]["value"] is None
    assert result["metrics"]["A1.9_net_to_gross_ratio"]["status"] == "NOT_APPLICABLE_ZERO_GROSS"


def test_invalid_token_invariant_is_not_computable() -> None:
    run = _run("native-lru")
    run["request_evidence"][0]["native_cached_prefix_tokens"] = 9

    result = compute_run_metrics(run)

    assert result["status"] == "NOT_COMPUTABLE"
