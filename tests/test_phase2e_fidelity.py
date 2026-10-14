from pathlib import Path

from kvopt.profiling.ingestion import RawRunArtifacts
from kvopt.profiling.phase2e_fidelity import (
    build_physical_evictions,
    build_targeted_forced_release_audit,
)


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


def test_targeted_audit_requires_ordered_selected_release_chain() -> None:
    snapshot = _event(
        1,
        "VLLM_PREFIX_SNAPSHOT",
        {
            "native_hash_process_id": "p1",
            "native_hash_block_size": 16,
            "ordered_native_cache_keys": ["key-a"],
            "block_ids": [7],
        },
    )
    snapshot["program_id"] = "agent-a"
    decision = _event(
        2,
        "FORCED_RELEASE_DECISION",
        {
            "candidates": [
                {
                    "program_id": "agent-a",
                    "prefix_id": "prefix-a",
                    "block_ids": [7],
                    "initially_reclaimable_block_ids": [7],
                },
                {
                    "program_id": "agent-b",
                    "prefix_id": "prefix-b",
                    "block_ids": [8],
                    "initially_reclaimable_block_ids": [8],
                },
            ],
            "selected_releases": [
                {
                    "program_id": "agent-a",
                    "prefix_id": "prefix-a",
                    "newly_eligible_block_ids": [7],
                }
            ],
            "original_free_queue": [
                {"block_id": 7, "eligibility_tier": 1}
            ],
        },
    )
    eviction = _event(
        3,
        "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
        {
            "native_hash_process_id": "p1",
            "native_cache_key_before": "key-a",
            "block_id": 7,
            "hash_removed_after": True,
        },
    )
    run = _run((snapshot, decision, eviction))
    run = RawRunArtifacts(
        run_dir=run.run_dir,
        run_id=run.run_id,
        manifest={"execution_status": "success"},
        trace=run.trace,
        replay=run.replay,
        events=run.events,
    )

    audit, candidates, _ = build_targeted_forced_release_audit(run)

    assert audit["status"] == "PASS"
    assert audit["p5_mapped_selected_evictions"] == 1
    assert [row["selected"] for row in candidates] == [True, False]
