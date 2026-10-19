import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.phase2g_a2_profile_range_audit import (
    audit_profile_range,
    build_abort_record,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "campaign"
    root.mkdir()
    trace = root / "s.trace.json"
    trace.write_text(
        json.dumps(
            {
                "requests": [
                    {"request_id": "p:1", "is_terminal": False},
                    {"request_id": "p:2", "is_terminal": False},
                    {"request_id": "p:3", "is_terminal": True},
                ]
            }
        ),
        encoding="utf-8",
    )
    config = root / "r.config.json"
    config.write_text(
        json.dumps(
            {
                "backend_options": {
                    "prefix_segments_by_request": {
                        "p:1": [["root", 256], ["tail", 256]],
                        "p:2": [["root", 256], ["tail", 288]],
                        "p:3": [["root", 256], ["tail", 400]],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "scenarios": [{"scenario_id": "s"}],
                "runs": [
                    {
                        "run_id": "r",
                        "scenario_id": "s",
                        "config": config.name,
                        "trace": trace.name,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    authorization = root / "authorization.json"
    authorization.write_text("{}\n", encoding="utf-8")
    return manifest, authorization, root


def test_range_audit_uses_nonterminal_runtime_query_path(tmp_path: Path) -> None:
    manifest, _authorization, _root = _fixture(tmp_path)

    audit = audit_profile_range(manifest)

    assert audit["required_profile_max_tokens"] == 544
    assert audit["minimum_new_measured_grid"] == [544]
    assert audit["out_of_legacy_range_scenarios"] == {"s": [544]}
    assert "656" not in audit["query_token_count_frequency_by_scenario_path"]
    assert audit["outcomes_inspected"] is False


def test_abort_record_requires_exact_preserved_failure(tmp_path: Path) -> None:
    manifest, authorization, _root = _fixture(tmp_path)
    runs = tmp_path / "runs"
    for index in range(92):
        output = runs / f"success-{index}"
        output.mkdir(parents=True)
        (output / "events.jsonl").write_text("{}\n", encoding="utf-8")
        (output / "run.json").write_text(
            json.dumps(
                {
                    "run_id": f"success-{index}",
                    "execution_status": "success",
                    "event_count": 1,
                    "failure_reason": None,
                }
            ),
            encoding="utf-8",
        )
    failed = runs / "f4-draw-06-a2-repeat-1"
    failed.mkdir(parents=True)
    (failed / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (failed / "stderr.log").write_text("traceback\n", encoding="utf-8")
    (failed / "run.json").write_text(
        json.dumps(
            {
                "run_id": "f4-draw-06-a2-repeat-1",
                "execution_status": "failed",
                "event_count": 299,
                "failure_reason": (
                    "ValueError: token_count is outside the supported profile range"
                ),
            }
        ),
        encoding="utf-8",
    )

    record = build_abort_record(
        manifest_path=manifest,
        authorization_path=authorization,
        run_root=runs,
    )

    assert record["campaign_status"] == "ABORTED_PROFILE_RANGE_INCOMPATIBILITY"
    assert record["status_counts"] == {"success": 92, "failed": 1}
    assert record["exclusion_from_formal_statistics"] is True
    assert record["manifest_sha256"] == _sha(manifest)


def test_abort_record_rejects_incomplete_preservation(tmp_path: Path) -> None:
    manifest, authorization, _root = _fixture(tmp_path)
    with pytest.raises(ValueError, match="status counts"):
        build_abort_record(
            manifest_path=manifest,
            authorization_path=authorization,
            run_root=tmp_path / "missing-runs",
        )
