from __future__ import annotations

import json
from pathlib import Path

from kvopt.workload.phase5_bfcl_result_audit import (
    audit_result_file,
    build_archive_audit,
)


def _source() -> list[dict[str, object]]:
    return [
        {
            "id": "web_search_0",
            "question": [[{"role": "user", "content": "question"}]],
            "involved_classes": ["WebSearchAPI"],
        }
    ]


def _frame() -> list[dict[str, object]]:
    return [
        {
            "case_id": "bfcl_web_search_0:snippet",
            "source_case_id": "web_search_0",
            "search_mode": "SNIPPET",
            "content_sha256": "a" * 64,
        }
    ]


def test_complete_semantic_trace_is_not_mislabeled_replay_ready(tmp_path: Path) -> None:
    row = {
        "id": "web_search_base_0",
        "result": [[[{"search_engine_query": "{}"}], "answer"]],
        "input_token_count": [[10]],
        "output_token_count": [[2]],
        "latency": [[0.1]],
        "inference_log": [
            {
                "begin_of_turn_query": [
                    {"role": "user", "content": "question"}
                ],
                "step_0": [
                    {
                        "role": "assistant",
                        "content": [{"search_engine_query": "{}"}],
                    },
                    {"role": "tool", "content": "[]"},
                ],
            }
        ],
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(row) + "\n")
    audit = audit_result_file(
        path=path,
        mode="SNIPPET",
        source_rows=_source(),
        frame_cases=_frame(),
        expected_blob_sha1="b" * 40,
        observed_blob_sha1="b" * 40,
    )
    detail = audit["case_details"][0]
    assert detail["semantic_agent_trace_complete"] is True
    assert detail["replay_ready_status"] == "NOT_READY"
    assert "NO_OBSERVED_TOOL_GAP_TIMESTAMPS" in detail["replay_blockers"]


def test_error_record_remains_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"id": "web_search_base_0", "result": "Error"}) + "\n")
    audit = audit_result_file(
        path=path,
        mode="SNIPPET",
        source_rows=_source(),
        frame_cases=_frame(),
        expected_blob_sha1="b" * 40,
        observed_blob_sha1="b" * 40,
    )
    assert audit["semantic_trace_incomplete_count"] == 1
    assert audit["case_details"][0]["qwen_token_materialization_status"] == "NOT_RECONSTRUCTABLE"


def test_combined_audit_does_not_treat_repository_license_as_content_clearance() -> None:
    file_audit = {
        "exact_frozen_id_coverage": True,
        "exact_frozen_frame_match": True,
        "record_count": 100,
        "semantic_trace_complete_count": 100,
        "replay_ready_count": 0,
    }
    report = build_archive_audit(
        repository_commit="c" * 40,
        repository_url="https://example.test/repo",
        license_id="Apache-2.0",
        repository_license_sha256="d" * 64,
        repository_readme_sha256="e" * 64,
        file_audits=[file_audit],
    )
    assert report["repository_license_does_not_clear_third_party_content"] is True
    assert report["frozen_frame_exact_id_coverage"] is True
    assert report["frozen_frame_exact_content_match"] is True
    assert report["direct_reuse_status"] == "NOT_READY"
