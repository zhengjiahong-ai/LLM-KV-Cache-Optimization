from __future__ import annotations

import csv
import json
import tarfile
from pathlib import Path

import pytest

from kvopt.profiling.phase3_algorithm_exposure import (
    _spearman,
    analyze_phase3_algorithm_exposure,
)


def test_spearman_handles_order_ties_and_degenerate_inputs() -> None:
    assert _spearman([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert _spearman([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)
    assert _spearman([1.0], [1.0]) is None
    assert _spearman([1.0, 1.0], [2.0, 3.0]) is None


def _event(run_id: str, index: int, kind: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "run_id": run_id,
        "event_index": index,
        "event_type": kind,
        "payload": payload,
    }


def _archive(path: Path) -> None:
    root = path.parent / "fixture"
    for group in range(1, 21):
        for condition in ("c1", "c2"):
            for arm in ("n0", "a0", "a1", "a2", "a3", "e0"):
                run_id = f"phase3-main-g{group:02d}-{condition}-r1-{arm}"
                events = [
                    _event(
                        run_id,
                        1,
                        "CONTROLLED_REPLAY_PRESSURE_COMPLETED",
                        {"attempt_count": 1},
                    )
                ]
                run = root / "bundle" / "native-runs" / run_id
                run.mkdir(parents=True)
                (run / "events.jsonl").write_text(
                    "\n".join(json.dumps(row) for row in events) + "\n",
                    encoding="utf-8",
                )
    with tarfile.open(path, "w:gz") as bundle:
        bundle.add(root / "bundle", arcname="bundle")


def test_analyzer_is_read_only_and_requires_fresh_output(tmp_path: Path) -> None:
    archive = tmp_path / "evidence.tar.gz"
    _archive(archive)
    original = archive.read_bytes()
    output = tmp_path / "analysis"
    summary = analyze_phase3_algorithm_exposure(archive, output)
    assert summary["main_run_count"] == 240
    assert archive.read_bytes() == original
    assert (output / "decision-audit.csv").is_file()
    assert (output / "sha256-manifest.txt").is_file()
    with (output / "group-condition-summary.csv").open(encoding="utf-8", newline="") as handle:
        cells = list(csv.DictReader(handle))
    assert len(cells) == 240
    assert {row["run_count"] for row in cells} == {"1"}
    assert {row["pressure_request_count"] for row in cells} == {"1"}
    with pytest.raises(FileExistsError):
        analyze_phase3_algorithm_exposure(archive, output)
