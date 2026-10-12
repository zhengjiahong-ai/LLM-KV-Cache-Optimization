import json
from pathlib import Path

from kvopt.profiling.phase2b_fidelity import build_fidelity_audit


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_report_uses_raw_events_and_preserves_history_limitation(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "run.json",
        {
            "run_id": "r",
            "execution_status": "success",
            "git_sha": "a" * 40,
            "git_dirty": False,
            "config_sha256": "b" * 64,
            "trace_sha256": "c" * 64,
            "contract_sha256": "d" * 64,
        },
    )
    _write_json(
        tmp_path / "fidelity-result.json",
        {
            "gates": [
                {
                    "gate": "G-INFLIGHT",
                    "requested": {"peak_inflight": 2},
                    "observed": {"peak_inflight": 2},
                    "status": "PASS",
                    "source_event_indices": [3, 4],
                    "scope": "native_request_lifecycle_overlap",
                    "runtime_identity": {"git_sha": "a" * 40},
                    "reason": "actual overlap",
                    "clock_domain": "system_monotonic",
                }
            ]
        },
    )
    events = [
        {"event_index": 0, "event_type": "REAL_RUNTIME_READY", "payload": {}},
        *[
            {
                "event_index": index,
                "event_type": "BACKEND_INPUT_MATERIALIZED",
                "program_id": program,
                "request_id": f"{program}:1",
                "payload": {
                    "kind": "turn",
                    "prefix_content_key": key,
                    "submitted_prefix_token_ids_sha256": digest,
                },
            }
            for index, program, key, digest in (
                (1, "shared-a", "shared", "same"),
                (2, "shared-b", "shared", "same"),
                (3, "distinct-c", "distinct", "other"),
            )
        ],
        *[
            {
                "event_index": index,
                "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
                "program_id": program,
                "request_id": request,
                "payload": {
                    "native_apc_block_hashes": hashes,
                    "native_cached_prefix_tokens": cached,
                    "native_queued_timestamp": 1.0,
                    "native_scheduler_admission_timestamp": 2.0,
                },
            }
            for index, program, request, hashes, cached in (
                (4, "shared-a", "shared-a:1", ["h"], 0),
                (5, "shared-b", "shared-b:1", ["h"], 16),
                (6, "distinct-c", "distinct-c:1", ["x"], 0),
                (11, "shared-a", "shared-a:2", ["h"], 8),
            )
        ],
        {
            "event_index": 7,
            "event_type": "TTL_HISTORY_INPUT_OBSERVED",
            "payload": {
                "queue_delay_history_sample_count": 0,
                "native_queue_duration_used_as_ttl_history": False,
            },
        },
        {"event_index": 8, "event_type": "FORCED_RELEASE_DECISION", "payload": {}},
        {
            "event_index": 9,
            "event_type": "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED",
            "payload": {
                "native_cache_key_before": "h",
                "hash_removed_after": True,
            },
        },
    ]
    (tmp_path / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    report = build_fidelity_audit(tmp_path)
    statuses = {gate["gate"]: gate["status"] for gate in report["gates"]}

    assert statuses["G-PREFIX-INPUT"] == "PASS"
    assert statuses["G-PREFIX-NATIVE"] == "PASS"
    assert statuses["G-PRESSURE"] == "PASS"
    assert statuses["G-TTL-HISTORY"] == "NOT_OBSERVABLE"
    assert statuses["G-LEGACY"] == "NOT_DEMONSTRATED"
