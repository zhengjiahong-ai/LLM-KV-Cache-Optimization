from pathlib import Path

import pytest

from kvopt.profiling.ingestion import ArtifactValidationError, RawRunArtifacts
from kvopt.profiling.runtime_evidence import (
    NATIVE_REQUEST_OBSERVATION,
    build_request_runtime_evidence_table,
    load_level_b_collection_design,
)

COLLECTION_DESIGN = (
    Path(__file__).parents[1]
    / "configs"
    / "phase2"
    / "h1-level-b-collection-design.json"
)


def _event(
    event_index: int,
    event_type: str,
    timestamp: float,
    clock_domain: str = "native-monotonic",
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "phase2.event.v1",
        "run_id": "run-a",
        "event_index": event_index,
        "event_type": event_type,
        "timestamp": timestamp,
        "clock_domain": clock_domain,
        "source": "test",
        "program_id": "agent-a",
        "request_id": "request-a1",
        "payload": payload or {},
    }


def _run(*events: dict[str, object]) -> RawRunArtifacts:
    return RawRunArtifacts(
        run_dir=Path("/artifacts/run-a"),
        run_id="run-a",
        manifest={"run_id": "run-a"},
        trace={"trace_id": "trace-a"},
        replay=(
            {
                "program_id": "agent-a",
                "request_id": "request-a1",
                "turn_index": 1,
                "planned_arrival_offset_seconds": 0.0,
                "tool_gap_seconds": None,
                "kind": "turn",
            },
        ),
        events=events,
    )


def test_runtime_evidence_derives_partial_hit_and_native_timings() -> None:
    row = build_request_runtime_evidence_table(
        (
            _run(
                _event(1, "VLLM_REQUEST_SUBMITTED", 10.0),
                _event(
                    2,
                    NATIVE_REQUEST_OBSERVATION,
                    10.8,
                    payload={
                        "eligible_prefix_tokens": 256,
                        "native_cached_prefix_tokens": 128,
                        "actual_prefill_tokens": 160,
                        "native_scheduler_admission_timestamp": 10.2,
                        "native_first_token_timestamp": 10.8,
                    },
                ),
                _event(3, "VLLM_REQUEST_COMPLETED", 11.5),
            ),
        )
    )[0]

    assert row.derived_apc_result == "PARTIAL_HIT"
    assert row.recomputed_prefill_tokens == 128
    assert row.recomputed_prefill_status == "available"
    assert row.native_queue_delay_seconds == pytest.approx(0.2)
    assert row.native_ttft_seconds == pytest.approx(0.8)
    assert row.native_e2e_seconds == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("eligible", "cached", "outcome"),
    [(256, 0, "MISS"), (256, 256, "FULL_HIT"), (0, 0, "NOT_APPLICABLE")],
)
def test_runtime_evidence_derives_apc_semantics(
    eligible: int,
    cached: int,
    outcome: str,
) -> None:
    row = build_request_runtime_evidence_table(
        (
            _run(
                _event(
                    1,
                    NATIVE_REQUEST_OBSERVATION,
                    1.0,
                    payload={
                        "eligible_prefix_tokens": eligible,
                        "native_cached_prefix_tokens": cached,
                    },
                )
            ),
        )
    )[0]

    assert row.derived_apc_result == outcome
    assert row.derived_apc_status == "available"


def test_runtime_evidence_preserves_missingness_without_proxy_inference() -> None:
    row = build_request_runtime_evidence_table((_run(),))[0]

    assert row.native_cached_prefix_tokens is None
    assert row.recomputed_prefill_tokens is None
    assert row.recomputed_prefill_status == "missing_native_token_count"
    assert row.derived_apc_result is None
    assert row.derived_apc_status == "missing_native_token_count"
    assert row.native_ttft_status == "missing_landmark"


def test_runtime_evidence_rejects_cached_count_above_eligible_count() -> None:
    run = _run(
        _event(
            1,
            NATIVE_REQUEST_OBSERVATION,
            1.0,
            payload={
                "eligible_prefix_tokens": 128,
                "native_cached_prefix_tokens": 256,
            },
        )
    )

    with pytest.raises(ArtifactValidationError, match="exceeds"):
        build_request_runtime_evidence_table((run,))


def test_runtime_evidence_rejects_prefill_below_derived_recompute() -> None:
    run = _run(
        _event(
            1,
            NATIVE_REQUEST_OBSERVATION,
            1.0,
            payload={
                "eligible_prefix_tokens": 256,
                "native_cached_prefix_tokens": 128,
                "actual_prefill_tokens": 64,
            },
        )
    )

    with pytest.raises(ArtifactValidationError, match="below derived"):
        build_request_runtime_evidence_table((run,))


def test_runtime_evidence_does_not_compare_incompatible_clocks() -> None:
    row = build_request_runtime_evidence_table(
        (
            _run(
                _event(
                    1,
                    "VLLM_REQUEST_SUBMITTED",
                    10.0,
                    "backend-clock",
                ),
                _event(
                    2,
                    NATIVE_REQUEST_OBSERVATION,
                    10.8,
                    payload={"native_first_token_timestamp": 10.8},
                ),
            ),
        )
    )[0]

    assert row.native_ttft_seconds is None
    assert row.native_ttft_status == "incompatible_clock_domain"


def test_level_b_design_predeclares_baseline_repeats_without_authorizing_runs() -> None:
    design = load_level_b_collection_design(COLLECTION_DESIGN)

    assert design["latency_calibration"]["identical_baseline_repeats"] == 5
    assert design["latency_calibration"]["epsilon_rule"] == (
        "max_absolute_deviation_from_baseline_mean"
    )
    assert not design["formal_collection_authorized"]
