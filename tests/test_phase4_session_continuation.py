"""Unit tests for the Phase 4 Session Continuation feasibility study."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "probes"
    / "phase4_session_continuation"
    / "study.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("phase4_session", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(module, group: str, program: str, label_60: int, prior: int, gap: float | None):
    return module.RequestRow(
        group=group,
        cell=f"{group}-c1",
        session=program,
        program=program,
        request_id=f"{program}:turn:{prior + 1}",
        timestamp=float(prior),
        prior_requests=prior,
        last_gap_seconds=gap,
        labels={window: (label_60 if window == 60.0 else 0) for window in module.WINDOWS},
    )


def test_gap_bucket_boundaries() -> None:
    module = _load_module()
    assert module.gap_bucket(None) == "none"
    assert module.gap_bucket(0.0) == "0-5s"
    assert module.gap_bucket(5.0) == "0-5s"
    assert module.gap_bucket(5.1) == "5-15s"
    assert module.gap_bucket(15.0) == "5-15s"
    assert module.gap_bucket(15.1) == "15-60s"
    assert module.gap_bucket(60.0) == "15-60s"
    assert module.gap_bucket(60.1) == ">60s"


def test_window_counts() -> None:
    module = _load_module()
    rows = [
        _row(module, "g01", "p1", 1, 0, None),
        _row(module, "g01", "p2", 0, 0, 1.0),
    ]
    counts = module.window_counts(rows)
    assert counts[60.0]["rows"] == 2
    assert counts[60.0]["positive"] == 1
    assert counts[60.0]["negative"] == 1


def test_train_rates_excludes_held_out_group() -> None:
    module = _load_module()
    rows = [
        _row(module, "g01", "p1", 1, 0, None),
        _row(module, "g02", "p2", 0, 0, None),
    ]
    rates = module.train_rates(rows, 60.0, "g01")
    # Only g02 remains in training: one negative row, smoothed toward 0.
    assert rates["global"] < 0.5
    assert rates["program"]["p2"] < 0.5
    assert "p1" not in rates["program"]


def test_predict_baselines_falls_back_to_global() -> None:
    module = _load_module()
    row = _row(module, "g01", "unseen", 1, 0, None)
    rates = {
        "global": 0.25,
        "program": {},
        "gap": {},
        "history": {},
    }
    prediction = module.predict_baselines(row, 60.0, rates)
    assert prediction["GLOBAL"] == 0.25
    assert prediction["PROGRAM"] == 0.25
    assert prediction["TOOL_GAP"] == 0.25
    assert prediction["SESSION_HISTORY"] == 0.25


def test_auc_score() -> None:
    module = _load_module()
    assert module.auc_score([1, 0, 1, 0], [0.9, 0.1, 0.8, 0.2]) == 1.0
    assert module.auc_score([1, 0], [0.1, 0.9]) == 0.0
    assert module.auc_score([1, 1], [0.1, 0.9]) is None
