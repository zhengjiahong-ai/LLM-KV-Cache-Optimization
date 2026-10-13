import json
from pathlib import Path

from kvopt.profiling.phase2c_native_pilot import evaluate_pilot_run


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _make_run(tmp_path: Path, *, pressure: bool = False) -> Path:
    _write_json(
        tmp_path / "run.json",
        {"run_id": "r", "execution_status": "success"},
    )
    expected = [
        {
            "request_id": "a",
            "program_id": "p1",
            "segments": [["root", 16]],
            "lcp_with": None,
            "eligible_prefix_tokens": 0,
        },
        {
            "request_id": "b",
            "program_id": "p2",
            "segments": [["root", 16], ["leaf", 16]],
            "lcp_with": "a",
            "eligible_prefix_tokens": 16,
        },
    ]
    _write_json(
        tmp_path / "config.json",
        {
            "phase2c_pilot": {
                "case_id": "case",
                "topology": "W-PRESSURE" if pressure else "W-ROOT-FORK",
                "repeat": 1,
                "pressure": "controlled_native_allocation" if pressure else "none",
                "expected_requests": expected,
            }
        },
    )
    events = []
    for index, request_id, digest in ((1, "a", "d1"), (4, "b", "d2")):
        events.append(
            {
                "event_index": index,
                "event_type": "BACKEND_INPUT_MATERIALIZED",
                "request_id": request_id,
                "payload": {
                    "submitted_prefix_token_ids_sha256": digest,
                    "prefix_segments": (
                        [["root", 16]] if request_id == "a" else [["root", 16], ["leaf", 16]]
                    ),
                },
            }
        )
    events.extend(
        [
            {
                "event_index": 2,
                "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
                "request_id": "a",
                "payload": {
                    "native_apc_block_hashes": ["h1"],
                    "native_hash_block_size": 16,
                    "native_hash_process_id": "42",
                    "native_cached_prefix_tokens": 0,
                },
            },
            {
                "event_index": 7,
                "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
                "request_id": "b",
                "payload": {
                    "native_apc_block_hashes": ["h1", "h2"],
                    "native_hash_block_size": 16,
                    "native_hash_process_id": "42",
                    "native_cached_prefix_tokens": 16,
                },
            },
        ]
    )
    if pressure:
        events.extend(
            [
                {"event_index": 3, "event_type": "FORCED_RELEASE_DECISION", "payload": {}},
                {
                    "event_index": 5,
                    "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
                    "payload": {
                        "hash_removed_after": True,
                        "native_hash_process_id": "42",
                    },
                },
            ]
        )
    events.sort(key=lambda row: row["event_index"])
    (tmp_path / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
    )
    return tmp_path


def test_topology_gate_uses_native_hash_lcp_and_separates_cold_request(
    tmp_path: Path,
) -> None:
    audit = evaluate_pilot_run(_make_run(tmp_path))

    assert audit["gate_status"] == "PASS"
    assert audit["requests"][0]["apc_outcome"] == "NO_REUSE_ELIGIBLE_PREFIX"
    assert audit["requests"][1]["actual_native_lcp_tokens"] == 16
    assert audit["requests"][1]["apc_outcome"] == "FULL_HIT"


def test_pressure_gate_requires_ordered_same_process_window(tmp_path: Path) -> None:
    audit = evaluate_pilot_run(_make_run(tmp_path, pressure=True))
    assert audit["pressure_gate"]["status"] == "PASS"

    events_path = tmp_path / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    eviction = next(
        row for row in events if row["event_type"] == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED"
    )
    eviction["event_index"] = 1
    events_path.write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")

    invalid = evaluate_pilot_run(tmp_path)
    assert invalid["pressure_gate"]["status"] == "NOT_DEMONSTRATED"
    assert invalid["gate_status"] == "NOT_DEMONSTRATED"


def test_native_hash_lcp_mismatch_fails_closed(tmp_path: Path) -> None:
    _make_run(tmp_path)
    events_path = tmp_path / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    observation = next(
        row
        for row in events
        if row["event_type"] == "VLLM_NATIVE_REQUEST_OBSERVATION" and row["request_id"] == "b"
    )
    observation["payload"]["native_apc_block_hashes"] = ["different", "h2"]
    events_path.write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")

    audit = evaluate_pilot_run(tmp_path)
    assert audit["gate_status"] == "FAIL"
    assert audit["requests"][1]["status"] == "FAIL"
