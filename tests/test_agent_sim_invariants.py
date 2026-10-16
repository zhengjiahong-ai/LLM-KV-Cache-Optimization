"""Phase 2F campaign-level invariants verified on the real scenario draws.

These pin the mechanism claims that the campaign report makes:

* D1 (in-band shallow-first) is bitwise identical to native LRU on every draw
  — i.e. the simulated native free-queue order *is* shallow-first inside a
  band, which is exactly the structural signal candidate v0 reverses;
* candidate v0 never produces a per-request hit-depth regression against
  native LRU (empirical shadow of the dominance theorem);
* negative-control draws (no reuse / no pressure) produce exactly zero
  recomputation under every arm.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kvopt.agent_sim.experiments import ARM_SPECS, run_arm
from kvopt.agent_sim.workload_gen import generate_campaign

CAMPAIGN_SEED = 20261016


def _traces():
    return generate_campaign(seed=CAMPAIGN_SEED)


def test_direction_reversal_is_bitwise_native() -> None:
    for trace in _traces():
        native = run_arm(trace, ARM_SPECS["A0"])
        reversal = run_arm(trace, ARM_SPECS["D1"])
        assert native.error is None and reversal.error is None
        assert [d.victim_block_ids for d in native.decisions] == [
            d.victim_block_ids for d in reversal.decisions
        ], trace.trace_id


def test_candidate_v0_has_no_per_request_regression() -> None:
    regressions = 0
    requests = 0
    for trace in _traces():
        native = run_arm(trace, ARM_SPECS["A0"])
        ours = run_arm(trace, ARM_SPECS["A2"])
        assert native.error is None and ours.error is None
        native_hits = {
            record.request_id: record.hit_depth
            for record in native.requests
            if record.window == "measured"
        }
        ours_hits = {
            record.request_id: record.hit_depth
            for record in ours.requests
            if record.window == "measured"
        }
        for request_id, depth in native_hits.items():
            challenger = ours_hits.get(request_id)
            if challenger is None:
                continue
            requests += 1
            if challenger < depth:
                regressions += 1
    assert requests > 1000
    assert regressions == 0, f"{regressions} per-request regressions"


def test_negative_controls_are_exactly_zero() -> None:
    for trace in _traces():
        if trace.family != "S7" or trace.draw > 6:
            continue
        for arm_id in ("A0", "A1", "A2", "A3"):
            result = run_arm(trace, ARM_SPECS[arm_id])
            assert result.error is None, (trace.trace_id, arm_id, result.error)
            recomputed = sum(
                record.recomputed_tokens
                for record in result.requests
                if record.window == "measured"
            )
            assert recomputed == 0, (trace.trace_id, arm_id, recomputed)
