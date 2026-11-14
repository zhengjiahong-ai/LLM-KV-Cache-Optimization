"""Unit tests for the P2 online future-reuse-depth study."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "probes" / "phase3_p2_depth" / "p2_study.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("p2_study", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_lcp() -> None:
    module = _load_module()
    assert module.lcp(("a", "b", "c"), ("a", "b", "d")) == 2
    assert module.lcp(("a",), ("b",)) == 0


def test_p2_choice_tie_prefers_a0() -> None:
    module = _load_module()
    views = [
        module.CandidateView("p1", 1, 10, 5, 0, 0, 0),
        module.CandidateView("p2", 1, 10, 5, 0, 0, 0),
    ]
    assert module.choose_p2(views, a0_index=0) == 0
    assert module.choose_p2(views, a0_index=1) == 1


def test_predict_depth_uses_prior_same_program_history() -> None:
    module = _load_module()
    requests = (
        module.STAGE0.RequestPoint("p1:1", "p1", 1, 32, 32, 32, ("a", "b")),
        module.STAGE0.RequestPoint("p1:2", "p1", 20, 48, 48, 48, ("a", "b", "c")),
    )
    trajectory = module.STAGE0.CellTrajectory(
        cell="g01-c1", requests=requests, decisions=(), r_a0=0, r_a0_recorded=0
    )
    # Prior pair LCP is 2; the chain under test is 3 blocks long.
    assert module.predict_depth(trajectory, "p1", 30, 3) == 2
    assert module.actual_future_depth(trajectory, ("a", "b", "c"), 30) == 0


def test_actual_future_depth_uses_later_requests() -> None:
    module = _load_module()
    requests = (
        module.STAGE0.RequestPoint("p1:1", "p1", 1, 32, 32, 32, ("a", "b")),
        module.STAGE0.RequestPoint("p1:2", "p1", 20, 48, 48, 48, ("a", "b", "c")),
    )
    trajectory = module.STAGE0.CellTrajectory(
        cell="g01-c1", requests=requests, decisions=(), r_a0=0, r_a0_recorded=0
    )
    assert module.actual_future_depth(trajectory, ("a", "b"), 0) == 2
    assert module.actual_future_depth(trajectory, ("a", "b"), 20) == 0
