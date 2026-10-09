from pathlib import Path

import pytest

from kvopt.profiling.ingestion import ArtifactValidationError, RawRunArtifacts
from kvopt.profiling.runtime_evidence import (
    NATIVE_REQUEST_OBSERVATION,
    build_request_runtime_evidence_table,
    derive_level_b_token_semantics,
    load_level_b_collection_design,
)

COLLECTION_DESIGN = (
    Path(__file__).parents[1]
    / "configs"
    / "phase2"
    / "h1-level-b-collection-design.json"
)
HASHES = ("01" * 32, "02" * 32, "03" * 32)


def _event(
    event_index: int,
    event_type: str,
    timestamp: float,
    clock_domain: str,
    *,
    payload: dict[str, object] | None = None,
    program_id: str = "agent-a",
    request_id: str = "request-a1",
    prefix_id: str | None = None,
    native_request_id: str | None = None,
) -> dict[str, object]:
    event: dict[str, object] = {
        "schema_version": "phase2.event.v1",
        "run_id": "run-a",
        "event_index": event_index,
        "event_type": event_type,
        "timestamp": timestamp,
        "clock_domain": clock_domain,
        "source": "test",
        "program_id": program_id,
        "request_id": request_id,
        "payload": payload or {},
    }
    if prefix_id is not None:
        event["prefix_id"] = prefix_id
    if native_request_id is not None:
        event["native_request_id"] = native_request_id
    return event


def _native_payload(
    *,
    prompt: int,
    cached: int,
    hashes: tuple[str, ...] = HASHES,
    process_id: str = "engine-123",
) -> dict[str, object]:
    return {
        "native_prompt_tokens": prompt,
        "native_cached_prefix_tokens": cached,
        "native_apc_block_hashes": list(hashes),
        "native_hash_block_size": 16,
        "native_hash_process_id": process_id,
        "native_hash_function": "sha256",
        "native_queued_timestamp": 10.0,
        "native_scheduler_admission_timestamp": 10.2,
        "native_first_token_timestamp": 10.8,
        "isolated_native_prefill_elapsed_seconds": 0.55,
    }


def _prefix_snapshot(
    event_index: int,
    *,
    hashes: tuple[str, ...] = HASHES,
    process_id: str = "engine-123",
    include_provenance: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "block_ids": list(range(1, len(hashes) + 1)),
        "reusable_token_count": len(hashes) * 16,
    }
    if include_provenance:
        payload.update(
            {
                "ordered_native_hashes": list(hashes),
                "hash_num_tokens": len(hashes) * 16,
                "native_hash_block_size": 16,
                "native_hash_process_id": process_id,
                "native_hash_function": "sha256",
            }
        )
    return _event(
        event_index,
        "VLLM_PREFIX_SNAPSHOT",
        9.0,
        "system_monotonic",
        payload=payload,
        request_id="materializing-request",
        prefix_id="logical-prefix-only",
    )


def _native_event(
    event_index: int,
    *,
    prompt: int,
    cached: int,
    hashes: tuple[str, ...] = HASHES,
    process_id: str = "engine-123",
    clock_domain: str = "engine_core_monotonic",
) -> dict[str, object]:
    return _event(
        event_index,
        NATIVE_REQUEST_OBSERVATION,
        10.8,
        clock_domain,
        payload=_native_payload(
            prompt=prompt,
            cached=cached,
            hashes=hashes,
            process_id=process_id,
        ),
        native_request_id="native-a1",
    )


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


def _table(*events: dict[str, object]):
    return build_request_runtime_evidence_table((_run(*events),))[0]


def test_cold_request_is_not_classified_as_eviction_miss() -> None:
    row = _table(_native_event(1, prompt=49, cached=0))

    assert row.availability == "AVAILABLE"
    assert row.eligible_prefix_tokens == 0
    assert row.actual_prefill_tokens == 49
    assert row.observed_recomputed_tokens == 0
    assert row.apc_outcome == "NO_REUSE_ELIGIBLE_PREFIX"


def test_exact_reusable_hit_has_zero_recomputed_tokens() -> None:
    row = _table(
        _prefix_snapshot(1, hashes=HASHES[:2]),
        _native_event(2, prompt=33, cached=32, hashes=HASHES[:2]),
    )

    assert row.eligible_prefix_tokens == 32
    assert row.actual_prefill_tokens == 1
    assert row.observed_recomputed_tokens == 0
    assert row.apc_outcome == "FULL_HIT"


def test_partial_hit_and_fresh_suffix_are_separated() -> None:
    row = _table(
        _prefix_snapshot(1, hashes=HASHES[:2]),
        _native_event(2, prompt=48, cached=16, hashes=HASHES),
    )

    assert row.eligible_prefix_tokens == 32
    assert row.native_cached_prefix_tokens == 16
    assert row.observed_recomputed_tokens == 16
    assert row.actual_prefill_tokens == 32
    assert row.actual_prefill_tokens == row.observed_recomputed_tokens + 16
    assert row.apc_outcome == "PARTIAL_HIT"


def test_full_loss_recomputes_all_previously_reusable_tokens() -> None:
    row = _table(
        _prefix_snapshot(1, hashes=HASHES[:2]),
        _native_event(2, prompt=33, cached=0, hashes=HASHES[:2]),
    )

    assert row.eligible_prefix_tokens == 32
    assert row.observed_recomputed_tokens == 32
    assert row.apc_outcome == "MISS"


def test_native_last_token_ceiling_limits_eligible_prefix() -> None:
    row = _table(
        _prefix_snapshot(1),
        _native_event(2, prompt=32, cached=16),
    )

    assert row.eligible_prefix_tokens == 16


def test_engine_core_timing_and_backend_e2e_keep_distinct_clocks() -> None:
    row = _table(
        _prefix_snapshot(1),
        _event(2, "VLLM_REQUEST_SUBMITTED", 20.0, "system_monotonic"),
        _native_event(3, prompt=49, cached=48),
        _event(4, "VLLM_REQUEST_COMPLETED", 21.5, "system_monotonic"),
    )

    assert row.native_queue_delay_seconds == pytest.approx(0.2)
    assert row.native_prefill_to_first_token_seconds == pytest.approx(0.6)
    assert row.isolated_native_prefill_elapsed_seconds == pytest.approx(0.55)
    assert row.isolated_native_prefill_elapsed_status == "available"
    assert row.backend_service_e2e_seconds == pytest.approx(1.5)


def test_non_engine_core_timestamps_are_timing_unavailable() -> None:
    row = _table(
        _native_event(
            1,
            prompt=49,
            cached=0,
            clock_domain="system_monotonic",
        )
    )

    assert row.native_queue_delay_seconds is None
    assert row.native_queue_delay_status == "incompatible_clock_domain"
    assert row.native_prefill_to_first_token_status == (
        "incompatible_clock_domain"
    )


def test_missing_native_timestamps_do_not_hide_token_evidence() -> None:
    event = _native_event(1, prompt=49, cached=0)
    payload = event["payload"]
    assert isinstance(payload, dict)
    payload["native_queued_timestamp"] = None
    payload["native_scheduler_admission_timestamp"] = None
    payload["native_first_token_timestamp"] = None

    row = _table(event)

    assert row.availability == "AVAILABLE"
    assert row.observed_recomputed_tokens == 0
    assert row.native_queue_delay_status == "missing_landmark"
    assert row.native_prefill_to_first_token_status == "missing_landmark"


def test_missing_isolated_prefill_is_explicitly_unavailable() -> None:
    event = _native_event(1, prompt=49, cached=0)
    payload = event["payload"]
    assert isinstance(payload, dict)
    payload.pop("isolated_native_prefill_elapsed_seconds")

    row = _table(event)

    assert row.isolated_native_prefill_elapsed_seconds is None
    assert row.isolated_native_prefill_elapsed_status == "missing_observation"


def test_non_positive_isolated_prefill_is_rejected() -> None:
    event = _native_event(1, prompt=49, cached=0)
    payload = event["payload"]
    assert isinstance(payload, dict)
    payload["isolated_native_prefill_elapsed_seconds"] = 0.0

    with pytest.raises(ArtifactValidationError, match="must be positive"):
        _table(event)


def test_missing_native_observation_preserves_explicit_missingness() -> None:
    row = _table()

    assert row.availability == "UNAVAILABLE"
    assert row.unavailable_reason == "native_request_observation_missing"
    assert row.observed_recomputed_tokens is None


def test_duplicate_native_observation_is_an_error() -> None:
    with pytest.raises(ArtifactValidationError, match="duplicate"):
        _table(
            _native_event(1, prompt=49, cached=0),
            _native_event(2, prompt=49, cached=0),
        )


def test_request_program_identity_mismatch_is_an_error() -> None:
    event = _native_event(1, prompt=49, cached=0)
    event["program_id"] = "different-program"

    with pytest.raises(ArtifactValidationError, match="mismatched program_id"):
        _table(event)


def test_cached_above_eligible_is_an_error_without_clamping() -> None:
    with pytest.raises(ArtifactValidationError, match="0 <= C <= E <= N"):
        _table(
            _prefix_snapshot(1, hashes=HASHES[:2]),
            _native_event(2, prompt=33, cached=48, hashes=HASHES[:2]),
        )


def test_eligible_above_prompt_is_an_error() -> None:
    with pytest.raises(ArtifactValidationError, match="0 <= C <= E <= N"):
        derive_level_b_token_semantics(
            native_prompt_tokens=16,
            eligible_prefix_tokens=32,
            native_cached_prefix_tokens=0,
        )


def test_missing_prior_hash_provenance_makes_eligible_unavailable() -> None:
    row = _table(
        _prefix_snapshot(1, include_provenance=False),
        _native_event(2, prompt=49, cached=0),
    )

    assert row.availability == "UNAVAILABLE"
    assert row.unavailable_reason == "prior_native_hash_provenance_unavailable"
    assert row.observed_recomputed_tokens is None


def test_different_process_hashes_are_never_compared() -> None:
    row = _table(
        _prefix_snapshot(1, process_id="other-engine"),
        _native_event(2, prompt=49, cached=0, process_id="engine-123"),
    )

    assert row.availability == "UNAVAILABLE"
    assert row.unavailable_reason == "no_compatible_prior_native_hash_provenance"


def test_prefix_identity_alone_cannot_produce_recompute_evidence() -> None:
    row = _table(
        _prefix_snapshot(1, include_provenance=False),
        _native_event(2, prompt=49, cached=0),
    )

    assert row.observed_recomputed_tokens is None


def test_level_b_design_authorizes_only_seam_validation() -> None:
    design = load_level_b_collection_design(COLLECTION_DESIGN)

    assert design["status"] == "AUTHORIZED_FOR_SEAM_VALIDATION"
    assert design["latency_calibration"]["identical_baseline_repeats"] == 5
    assert not design["formal_h1_outcome_execution_authorized"]
