from kvopt.workload.phase2b_fidelity import (
    STATUS_NOT_DEMONSTRATED,
    STATUS_PASS,
    PressureObservation,
    build_pressure_gate,
)


def _identity() -> dict[str, object]:
    return {"vllm": "0.27.1", "process_id": "123"}


def test_pressure_gate_requires_all_three_evidence_levels() -> None:
    result = build_pressure_gate(
        PressureObservation(
            logical_release_event_indices=(10,),
            native_hashed_eviction_event_indices=(12,),
            subsequent_apc_event_indices=(15,),
            native_cache_keys_before_eviction=("sha256:abc",),
            hash_cleanup_confirmed=True,
            subsequent_native_cached_prefix_tokens=0,
        ),
        runtime_identity=_identity(),
    )

    assert result.status == STATUS_PASS
    assert result.source_event_indices == (10, 12, 15)


def test_logical_release_alone_never_passes_native_eviction_gate() -> None:
    result = build_pressure_gate(
        PressureObservation(
            logical_release_event_indices=(10,),
            native_hashed_eviction_event_indices=(),
            subsequent_apc_event_indices=(),
            native_cache_keys_before_eviction=(),
            hash_cleanup_confirmed=False,
            subsequent_native_cached_prefix_tokens=None,
        ),
        runtime_identity=_identity(),
    )

    assert result.status == STATUS_NOT_DEMONSTRATED
    assert "logical release alone" in result.reason
