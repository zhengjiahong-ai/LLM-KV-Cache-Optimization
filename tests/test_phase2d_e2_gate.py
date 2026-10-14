import json
from pathlib import Path

from kvopt.profiling.phase2d_e2 import evaluate_e2


def test_gate_fails_when_expected_runs_are_missing(tmp_path: Path) -> None:
    result = evaluate_e2(tmp_path)

    assert result["status"] == "FAIL"
    assert result["observed_run_ids"] == []


def test_gate_fails_on_non_aligned_cached_tokens(tmp_path: Path) -> None:
    run_dir = tmp_path / "e2-shared-root-repeat-1"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps({"run_id": run_dir.name, "execution_status": "success"}),
        encoding="utf-8",
    )
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "cache": {"block_size": 16},
                "phase2d_stage": {
                    "case_id": "e2-shared-root",
                    "expected_shared_protected_blocks": 8,
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trace.json").write_text(
        json.dumps({"requests": [{"request_id": "a"}]}), encoding="utf-8"
    )
    events = [
        {
            "event_index": 1,
            "event_type": "BACKEND_INPUT_MATERIALIZED",
            "request_id": "a",
            "payload": {},
        },
        {
            "event_index": 2,
            "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
            "request_id": "a",
            "payload": {
                "native_cached_prefix_tokens": 15,
                "native_prompt_tokens": 17,
            },
        },
    ]
    (run_dir / "events.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in events), encoding="utf-8"
    )

    result = evaluate_e2(tmp_path)

    assert result["status"] == "FAIL"
    assert "invalid cached-token evidence for a" in result["runs"][0]["reasons"]
