import json
from pathlib import Path

import pytest

from kvopt.workload.continuum_w1a_report import _lcp_length, build_report


def test_lcp_length_uses_exact_token_identity() -> None:
    assert _lcp_length([1, 2, 3], [1, 2, 4]) == 2
    assert _lcp_length([1], [1, 2]) == 1
    assert _lcp_length([1], [2]) == 0


def test_report_module_is_json_serializable() -> None:
    # Protect the report's machine-readable surface from non-JSON scalar types.
    assert json.dumps({"path": str(Path("runs")), "lcp": _lcp_length([], [])})


def test_report_rejects_missing_frozen_task(tmp_path: Path) -> None:
    run_dir = tmp_path / "task-a"
    run_dir.mkdir()
    (run_dir / "run.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cohort mismatch"):
        build_report(tmp_path, frozen_instance_ids=("task-a", "task-b"))
