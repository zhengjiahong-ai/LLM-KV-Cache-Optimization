"""Unit tests for the Stage 0 A0-anchored prefix-state oracle."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "probes"
    / "phase3_stage0_oracle"
    / "stage0_oracle.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("stage0_oracle", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def stage0():
    return _load_module()


def _trajectory(stage0):
    requests = (
        stage0.RequestPoint(
            request_id="p1:turn:1",
            program_id="p1",
            event_index=1,
            n=32,
            e=32,
            c=32,
            hashes=("a", "b"),
        ),
        stage0.RequestPoint(
            request_id="p1:turn:2",
            program_id="p1",
            event_index=20,
            n=32,
            e=32,
            c=32,
            hashes=("a", "b"),
        ),
    )
    candidates = (
        stage0.Candidate("p1", "prefix-1", 1, frozenset({"b"}), 2),
        stage0.Candidate("p2", "prefix-2", 1, frozenset({"a"}), 1),
    )
    decisions = (
        stage0.Decision(
            cell="g01-c1",
            event_index=10,
            need=1,
            candidates=candidates,
            a0_index=0,
            matched_count=1,
            a0_victim_subset_physical=True,
            a0_selected_program="p1",
        ),
    )
    return stage0.CellTrajectory(
        cell="g01-c1",
        requests=requests,
        decisions=decisions,
        r_a0=0,
        r_a0_recorded=0,
    )


def test_a0_path_is_exact_by_construction(stage0) -> None:
    trajectory = _trajectory(stage0)
    result = stage0.simulate_path(trajectory, stage0.a0_choices(trajectory))
    assert result.total == trajectory.r_a0
    assert [row["C_counterfactual"] for row in result.per_request] == [32, 32]


def test_alternative_choice_is_scored_over_both_requests(stage0) -> None:
    trajectory = _trajectory(stage0)
    result = stage0.simulate_path(trajectory, (1,))
    assert result.total == 32
    assert result.per_request[1]["C_counterfactual"] == 0
    assert result.per_request[1]["recomputed"] == 32


def test_oracle_does_not_outperform_a0_when_a0_is_optimal(stage0) -> None:
    trajectory = _trajectory(stage0)
    oracle = stage0.enumerate_oracle(trajectory)
    assert oracle["oracle_gain_tokens"] == 0
    assert oracle["oracle_choices"] == [0]
    assert oracle["a0_exact"] is True


def test_p2_depth_score_uses_future_same_program_reuse(stage0) -> None:
    trajectory = _trajectory(stage0)
    # A0 candidate truncates p1's second request at depth 2: one cached block lost.
    assert stage0.p2_depth_score(trajectory, 0, 0) == 16
    # The p2 candidate has no future p2 request, so the same-program proxy is 0.
    assert stage0.p2_depth_score(trajectory, 0, 1) == 0
