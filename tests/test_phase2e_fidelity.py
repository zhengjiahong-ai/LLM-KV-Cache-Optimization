from pathlib import Path

from kvopt.profiling.ingestion import RawRunArtifacts
from kvopt.profiling.phase2e_fidelity import build_physical_evictions


def _run(events: tuple[dict[str, object], ...]) -> RawRunArtifacts:
    return RawRunArtifacts(
        run_dir=Path("/tmp/run"),
        run_id="run",
        manifest={"run_id": "run"},
        trace={},
        replay=(),
        events=events,
    )


def _event(index: int, kind: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "event_index": index,
        "event_type": kind,
        "timestamp": float(index),
        "payload": payload,
    }


def test_physical_eviction_maps_only_matching_key_process_and_slot() -> None:
    rows = build_physical_evictions(
        _run(
            (
                _event(
                    1,
                    "VLLM_PREFIX_SNAPSHOT",
                    {
                        "native_hash_process_id": "p1",
                        "native_hash_block_size": 16,
                        "ordered_native_cache_keys": ["key-a"],
                        "block_ids": [7],
                    },
                ),
                _event(
                    2,
                    "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
                    {
                        "native_hash_process_id": "p1",
                        "native_cache_key_before": "key-a",
                        "block_id": 7,
                        "hash_removed_after": True,
                    },
                ),
            )
        )
    )

    assert rows[0]["prefix_position_status"] == "MAPPED"
    assert rows[0]["prefix_token_start"] == 0
    assert rows[0]["prefix_token_end"] == 16


def test_physical_eviction_rejects_slot_reuse_with_different_key() -> None:
    rows = build_physical_evictions(
        _run(
            (
                _event(
                    1,
                    "VLLM_PREFIX_SNAPSHOT",
                    {
                        "native_hash_process_id": "p1",
                        "native_hash_block_size": 16,
                        "ordered_native_cache_keys": ["old-key"],
                        "block_ids": [7],
                    },
                ),
                _event(
                    2,
                    "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
                    {
                        "native_hash_process_id": "p1",
                        "native_cache_key_before": "new-key",
                        "block_id": 7,
                        "hash_removed_after": True,
                    },
                ),
            )
        )
    )

    assert rows[0]["prefix_position_status"] == "NOT_IDENTIFIABLE"
    assert rows[0]["prefix_block_index"] is None
