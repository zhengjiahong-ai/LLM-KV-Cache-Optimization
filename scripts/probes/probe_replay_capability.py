"""Confirm, by introspection rather than by reading, that the existing replay
layer cannot support block-level victim selection.

Backs section 6.4.1 of the joint design document. Every assertion below states a
structural gap, so this script also acts as a tripwire: once the replay layer
gains block-level support, this probe fails and the document must be updated.

Run with the package importable, e.g.::

    PYTHONPATH=src python scripts/probes/probe_replay_capability.py
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:  # allow running without PYTHONPATH
    sys.path.insert(0, str(_SRC))

from kvopt.costaware.replay import (  # noqa: E402
    DecisionSnapshot,
    QueueBlock,
    ReleaseStrategy,
    ReplayOutcome,
)


def main() -> int:
    print("=== QueueBlock fields ===")
    queue_fields = [f.name for f in dataclasses.fields(QueueBlock)]
    print(" ", queue_fields)
    assert set(queue_fields) == {"block_id", "has_block_hash", "native_lru_rank"}
    print("  -> no depth, no chain membership => Delta_c(b) = q_c*B*(j_c-d)^+"
          " is not evaluable")

    print("\n=== DecisionSnapshot fields ===")
    snapshot_fields = [f.name for f in dataclasses.fields(DecisionSnapshot)]
    print(" ", snapshot_fields)
    assert "block_ids_by_key" not in snapshot_fields
    assert "depth_by_block" not in snapshot_fields
    assert "owners_by_block" in snapshot_fields and "ranking_by_block" in snapshot_fields
    print("  -> per-entry block_ids is dropped; only ownership and ranking survive")

    print("\n=== ReplayOutcome fields ===")
    outcome_fields = [f.name for f in dataclasses.fields(ReplayOutcome)]
    print(" ", outcome_fields)
    assert "evicted_blocks" not in outcome_fields
    assert "evicted" not in outcome_fields
    assert "eligible_blocks_final" in outcome_fields
    print("  -> only a COUNT of final eligible blocks; the evicted set S is never"
          " materialised")

    print("\n=== ReleaseStrategy protocol methods ===")
    methods = [m for m in dir(ReleaseStrategy) if not m.startswith("_")]
    print(" ", methods)
    assert methods == ["pick_next"]
    print("  -> there is no VictimStrategy analogue for choosing a block")

    print("\nALL CHECKS PASSED - block-level support is absent, as documented")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
