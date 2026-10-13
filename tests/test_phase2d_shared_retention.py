import json
from pathlib import Path

from kvopt.profiling.phase2d_shared_retention import audit_shared_retention


def _write_run(
    root: Path,
    *,
    candidates: list[dict[str, object]],
    snapshots: list[dict[str, object]],
) -> Path:
    run = root / "run"
    run.mkdir()
    events = [
        *snapshots,
        {
            "event_index": 10,
            "event_type": "FORCED_RELEASE_DECISION",
            "run_id": "run",
            "timestamp": 1.0,
            "payload": {"candidates": candidates},
        },
    ]
    (run / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
    )
    return root


def _candidate(
    program: str, prefix: str, blocks: list[int], relief: list[int]
) -> dict[str, object]:
    return {
        "program_id": program,
        "prefix_id": prefix,
        "block_ids": blocks,
        "initially_reclaimable_block_ids": relief,
    }


def _snapshot(
    index: int, program: str, prefix: str, blocks: list[int], hashes: list[str]
) -> dict[str, object]:
    return {
        "event_index": index,
        "event_type": "VLLM_PREFIX_SNAPSHOT",
        "program_id": program,
        "prefix_id": prefix,
        "payload": {
            "block_ids": blocks,
            "ordered_native_hashes": hashes,
            "ordered_native_cache_keys": [f"{value}-key" for value in hashes],
            "native_hash_process_id": "42",
        },
    }


def test_audit_observes_shared_protected_physical_block(tmp_path: Path) -> None:
    root = _write_run(
        tmp_path,
        candidates=[
            _candidate("a", "pa", [1], []),
            _candidate("b", "pb", [1], []),
        ],
        snapshots=[
            _snapshot(1, "a", "pa", [1], ["hash"]),
            _snapshot(2, "b", "pb", [1], ["hash"]),
        ],
    )

    result = audit_shared_retention(root)

    assert result["conclusion"] == "OBSERVED_SHARED_PROTECTED"
    assert result["summary"]["multiple_protected_owner_decision_count"] == 1


def test_audit_reports_observed_no_shared_when_mapping_is_complete(tmp_path: Path) -> None:
    root = _write_run(
        tmp_path,
        candidates=[_candidate("a", "pa", [1], [1])],
        snapshots=[_snapshot(1, "a", "pa", [1], ["hash-a"])],
    )

    result = audit_shared_retention(root)

    assert result["conclusion"] == "OBSERVED_NO_SHARED_PROTECTED"
    assert result["decisions"][0]["marginal_relief_counts"] == [1]


def test_audit_fails_closed_when_owner_mapping_is_missing(tmp_path: Path) -> None:
    root = _write_run(
        tmp_path,
        candidates=[_candidate("a", "pa", [1], [1])],
        snapshots=[],
    )

    result = audit_shared_retention(root)

    assert result["conclusion"] == "NOT_OBSERVABLE"
    assert result["summary"]["not_observable_decision_count"] == 1
