from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from kvopt.workload.phase5_campaign_plan import (
    balanced_latin_square,
    materialize_campaign_plan,
)
from kvopt.workload.phase5_formal_archive import (
    FormalArchiveError,
    create_formal_campaign_archive,
)
from kvopt.workload.phase5_formal_manifests import build_run_result_manifest


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan():
    groups = {"SWE_BENCH": [f"s{index}" for index in range(4)]}
    square = balanced_latin_square()
    orders = {}
    ordinal = 0
    for stratum, group_ids in groups.items():
        for group_id in group_ids:
            for repeat in range(1, 4):
                orders[f"{stratum}:{group_id}:r{repeat}"] = square[ordinal % 6]
                ordinal += 1
    all_groups = [group_id for rows in groups.values() for group_id in rows]
    return materialize_campaign_plan(
        phase="CALIBRATION",
        groups=groups,
        repeats=3,
        execution_orders=orders,
        workload_seal_sha256_by_group={group_id: "a" * 64 for group_id in all_groups},
        arrival_sha256_by_group={group_id: "b" * 64 for group_id in all_groups},
        protocol_sha256="c" * 64,
    )


def _source(tmp_path: Path):
    root = tmp_path / "evidence"
    plan = _plan()
    _write_json(root / "campaign-plan.json", plan)
    for name in ("protocol-bundle.json", "gate-ledger.json", "analysis.json"):
        _write_json(root / name, {"status": "CPU_TEST"})
    index = []
    for row in plan["runs"]:
        run_id = row["run_id"]
        run_root = root / "runs" / run_id
        input_path = run_root / "run-input.json"
        input_manifest = {"run_id": run_id, "frozen": True}
        _write_json(input_path, input_manifest)
        evidence = {}
        evidence_sha = {}
        for evidence_name in (
            "planned_events",
            "native_events",
            "terminal_events",
            "exposure_events",
            "decision_physical_events",
            "downstream_observations",
            "mechanism_observations_m0_m5",
        ):
            path = run_root / f"{evidence_name}.jsonl"
            path.write_text("{}\n", encoding="utf-8")
            evidence[evidence_name] = path.relative_to(root).as_posix()
            evidence_sha[evidence_name] = _sha(path)
        metrics_path = run_root / "derived-metrics.json"
        _write_json(metrics_path, {"status": "PASS"})
        result = build_run_result_manifest(
            run_input_manifest=input_manifest,
            status="PASS",
            actual_enqueue_sequence_sha256="d" * 64,
            evidence_sha256=evidence_sha,
            derived_metrics_sha256=_sha(metrics_path),
            started_at="2026-11-19T00:00:00Z",
            ended_at="2026-11-19T00:00:01Z",
            failure_reason=None,
        )
        result_path = run_root / "run-result.json"
        _write_json(result_path, result)
        index.append(
            {
                "run_id": run_id,
                "input_manifest": input_path.relative_to(root).as_posix(),
                "result_manifest": result_path.relative_to(root).as_posix(),
                "derived_metrics": metrics_path.relative_to(root).as_posix(),
                "evidence": evidence,
            }
        )
    _write_json(root / "run-index.json", {"runs": index})
    return root, plan, index


def test_whole_calibration_archive_round_trip(tmp_path: Path) -> None:
    root, _, _ = _source(tmp_path)
    report = create_formal_campaign_archive(
        source_root=root, archive_path=tmp_path / "campaign.tar.gz"
    )
    assert report["status"] == "PASS"
    assert report["run_count"] == 72
    assert report["run_status_counts"] == {"PASS": 72}
    assert report["archive_validation_status"] == "PASS"
    assert report["execution_authorization_effect"] == "NONE"


def test_missing_run_and_changed_evidence_fail_closed(tmp_path: Path) -> None:
    root, _, index = _source(tmp_path)
    changed_index = deepcopy(index)
    changed_index.pop()
    _write_json(root / "run-index.json", {"runs": changed_index})
    with pytest.raises(FormalArchiveError, match="differs"):
        create_formal_campaign_archive(
            source_root=root, archive_path=tmp_path / "missing.tar.gz"
        )

    _write_json(root / "run-index.json", {"runs": index})
    evidence_path = root / index[0]["evidence"]["native_events"]
    evidence_path.write_text('{"changed":true}\n', encoding="utf-8")
    with pytest.raises(FormalArchiveError, match="SHA-256"):
        create_formal_campaign_archive(
            source_root=root, archive_path=tmp_path / "changed.tar.gz"
        )


def test_failed_run_is_archived_without_fabricated_metrics(tmp_path: Path) -> None:
    root, _, index = _source(tmp_path)
    first = index[0]
    input_manifest = json.loads(
        (root / first["input_manifest"]).read_text(encoding="utf-8")
    )
    old_result = json.loads(
        (root / first["result_manifest"]).read_text(encoding="utf-8")
    )
    failed = build_run_result_manifest(
        run_input_manifest=input_manifest,
        status="FAIL_CLOSED",
        actual_enqueue_sequence_sha256=None,
        evidence_sha256=old_result["evidence_sha256"],
        derived_metrics_sha256=None,
        started_at="2026-11-19T00:00:00Z",
        ended_at="2026-11-19T00:00:01Z",
        failure_reason="injected failure",
    )
    _write_json(root / first["result_manifest"], failed)
    (root / first["derived_metrics"]).unlink()
    first["derived_metrics"] = None
    _write_json(root / "run-index.json", {"runs": index})
    report = create_formal_campaign_archive(
        source_root=root, archive_path=tmp_path / "failed.tar.gz"
    )
    assert report["run_status_counts"] == {"FAIL_CLOSED": 1, "PASS": 71}
