"""Unit tests for the P2 candidate-chain-conditioned online study."""

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


def _trajectory(module):
    requests = (
        module.STAGE0.RequestPoint("p1:1", "p1", 1, 32, 32, 32, ("a", "b")),
        module.STAGE0.RequestPoint("p1:2", "p1", 20, 48, 48, 48, ("a", "b", "c")),
        module.STAGE0.RequestPoint("p2:1", "p2", 25, 32, 32, 32, ("x", "y")),
    )
    return module.STAGE0.CellTrajectory(
        cell="g01-c1", requests=requests, decisions=(), r_a0=0, r_a0_recorded=0
    )


def test_lcp() -> None:
    module = _load_module()
    assert module.lcp(("a", "b", "c"), ("a", "b", "d")) == 2
    assert module.lcp(("a",), ("b",)) == 0


def test_p2_choice_tie_prefers_a0() -> None:
    module = _load_module()
    view = module.CandidateView(
        "p1",
        1,
        10,
        5,
        {method: 0 for method in module.METHODS},
        {method: 0 for method in module.METHODS},
        0,
    )
    views = [
        view,
        module.CandidateView(
            "p2",
            1,
            10,
            5,
            {method: 0 for method in module.METHODS},
            {method: 0 for method in module.METHODS},
            0,
        ),
    ]
    assert module.choose_p2(views, "P2_C_CHAIN_WEIGHTED", a0_index=0) == 0
    assert module.choose_p2(views, "P2_C_CHAIN_WEIGHTED", a0_index=1) == 1


def test_predict_depth_uses_prior_same_program_history() -> None:
    module = _load_module()
    trajectory = _trajectory(module)
    # P2-A pairwise LCP of prior p1 chains is 2.
    assert (
        module.predict_depth(
            trajectory,
            method="P2_A_ORIGINAL_MAX",
            program="p1",
            chain_hashes=("a", "b", "c"),
            event_index=30,
        )
        == 2
    )
    # P2-B excludes the source chain itself; only one other p1 chain remains.
    assert (
        module.predict_depth(
            trajectory,
            method="P2_B_CHAIN_MAX",
            program="p1",
            chain_hashes=("a", "b", "c"),
            event_index=30,
            exclude_event_index=20,
        )
        == 2
    )


def test_future_prefix_demand_overlap_uses_later_requests() -> None:
    module = _load_module()
    trajectory = _trajectory(module)
    assert module.future_prefix_demand_overlap(trajectory, ("a", "b"), 0) == 2
    assert module.future_prefix_demand_overlap(trajectory, ("a", "b"), 20) == 0


def test_victim_suffix_must_be_proven_or_fail_closed() -> None:
    module = _load_module()
    trajectory = _trajectory(module)
    # ("b",) is a suffix of p1:1; it is proven.
    source = module.find_candidate_chain(
        trajectory,
        program="p1",
        need=1,
        victim_hashes=frozenset({"b"}),
        event_index=30,
    )
    assert source is not None
    # ("a", "c") is not a contiguous suffix of any p1 chain.
    missing = module.find_candidate_chain(
        trajectory,
        program="p1",
        need=2,
        victim_hashes=frozenset({"a", "c"}),
        event_index=30,
    )
    assert missing is None
    view, reason = module.build_view(
        trajectory,
        program="p1",
        need=2,
        victim_hashes=frozenset({"a", "c"}),
        decision_event_index=30,
    )
    assert view is None
    assert reason == "victim_hashes_not_a_contiguous_suffix_of_any_prior_chain"
