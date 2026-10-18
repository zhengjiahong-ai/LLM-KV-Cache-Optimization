"""A2 block-level mechanism study driver.

Answers, on recorded evidence and with the corrected geometry:

RQ1  Is there a real block-level selection space? -- measured as *victim-set*
     divergence under a fixed entry release, never as ordering difference.
RQ2  Can the difference be explained by decision-time cost information? -- measured
     as chain-window depth ordering, ``q`` versus rank ordering, and how often
     pressure actually forces hash-carrying blocks to be touched.
RQ3  Would A2 be worth a native implementation? -- reported as an explicit gate,
     plus the interface gap that currently blocks it.

Usage::

    python -m kvopt.costaware.a2_compare --corpus <artifact-root> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

from .a2_evidence import build_geometry, decisions_for_run
from .a2_geometry import (
    ChainKey,
    DecisionDivergence,
    DecisionGeometry,
    evaluate,
)


def chain_windows(geometry: DecisionGeometry) -> tuple[int, int, int, int]:
    """(native_already_deepest, depth_inverted, non_monotone, total) windows.

    A smaller ``native_lru_rank`` means colder, so it is evicted earlier.

    - rank **decreasing** with depth  => deeper blocks are colder => native already
      evicts deepest-first, which is optimal inside the chain, so there is no depth
      decision to make;
    - rank **increasing** with depth  => shallower blocks are colder => native moves
      the gap inward on its first pick, extending the missing suffix the fastest,
      which is the case a depth rule could improve on.

    Both are measured against **true content depth**, never against rank.
    """
    per_chain: dict[ChainKey, list[tuple[int, int]]] = defaultdict(list)
    for block in geometry.blocks.values():
        if not block.has_block_hash:
            continue
        for membership in block.memberships:
            per_chain[membership.chain].append((membership.depth, block.native_rank))
    ordered = inverted = non_monotone = total = 0
    for pairs in per_chain.values():
        if len(pairs) < 3:
            continue
        total += 1
        pairs.sort()
        ranks = [rank for _, rank in pairs]
        if all(ranks[i] > ranks[i + 1] for i in range(len(ranks) - 1)):
            ordered += 1
        elif all(ranks[i] < ranks[i + 1] for i in range(len(ranks) - 1)):
            inverted += 1
        else:
            non_monotone += 1
    return ordered, inverted, non_monotone, total


def inverted_touched_chains(
    geometry: DecisionGeometry, victim: Sequence[int]
) -> int:
    """Inverted-depth chains that the victim set actually touches.

    A depth inversion only matters if the rule is forced to evict from that chain.
    An inversion sitting in a chain the demand never reaches is real headroom that
    the decision cannot express, which is a different statement from "no headroom".
    """
    touched = {
        membership.chain
        for block_id in victim
        for membership in geometry.blocks[block_id].memberships
    }
    count = 0
    for chain in touched:
        pairs = sorted(
            (membership.depth, block.native_rank)
            for block in geometry.blocks.values()
            for membership in block.memberships
            if membership.chain == chain
        )
        if len(pairs) < 3:
            continue
        ranks = [rank for _, rank in pairs]
        if all(ranks[i] < ranks[i + 1] for i in range(len(ranks) - 1)):
            count += 1
    return count


def _shape(row: DecisionDivergence) -> dict[str, object]:
    return {
        "run_id": row.run_id,
        "decision_event_index": row.decision_event_index,
        "need": row.need,
        "legal_count": row.legal_count,
        "chain_count": row.chain_count,
        "shared_blocks": row.shared_block_count,
        "native_blocks": list(row.native.blocks),
        "cost_aware_blocks": list(row.cost_aware.blocks),
        "victim_set_differs": row.victim_set_differs,
        "native_expected_loss": row.native.expected_recompute,
        "cost_aware_expected_loss": row.cost_aware.expected_recompute,
        "expected_loss_delta": (
            row.cost_aware.expected_recompute - row.native.expected_recompute
        ),
        "q_order_agrees_with_rank": row.q_order_agrees_with_rank,
    }


def summarise(
    geometries: Sequence[tuple[DecisionDivergence, DecisionGeometry]],
) -> dict[str, object]:
    total = len(geometries)
    scorable = [pair for pair in geometries if pair[0].scorable]
    gaps = Counter(
        reason for _, geometry in geometries for reason in geometry.gaps.values()
    )
    freedom = [pair for pair in geometries if pair[0].legal_count > pair[0].need]
    scorable_freedom = [pair for pair in freedom if pair[0].scorable]
    differs = [pair for pair in geometries if pair[0].victim_set_differs]
    scorable_differs = [pair for pair in scorable if pair[0].victim_set_differs]
    choice_differs = [pair for pair in scorable_freedom if pair[0].victim_set_differs]

    ordered = inverted = non_monotone = windows = 0
    inverted_touched_windows = 0
    decisions_with_reachable_inversion = 0
    decisions_with_reachable_inversion_scorable = 0
    for row, geometry in geometries:
        o, i, n, t = chain_windows(geometry)
        ordered += o
        inverted += i
        non_monotone += n
        windows += t
        reach = inverted_touched_chains(geometry, row.native.blocks)
        inverted_touched_windows += reach
        if reach:
            decisions_with_reachable_inversion += 1
            if row.scorable:
                decisions_with_reachable_inversion_scorable += 1

    q_compared = [
        pair[0] for pair in geometries if pair[0].q_order_agrees_with_rank is not None
    ]
    delta = [
        pair[0].cost_aware.expected_recompute - pair[0].native.expected_recompute
        for pair in scorable
    ]
    return {
        "decisions": total,
        "scorable_decisions": len(scorable),
        "decisions_with_gap": sum(1 for pair in geometries if not pair[0].scorable),
        "observation_gaps": dict(sorted(gaps.items())),
        "multi_chain_decisions": sum(1 for pair in geometries if pair[0].chain_count >= 2),
        "shared_blocks_seen": sum(pair[0].shared_block_count for pair in geometries),
        "decisions_with_real_freedom": len(freedom),
        "scorable_decisions_with_freedom": len(scorable_freedom),
        "order_differs": sum(1 for pair in geometries if pair[0].order_differs),
        "victim_set_differs": len(differs),
        "victim_set_differs_scorable": len(scorable_differs),
        "victim_set_differs_with_freedom": len(choice_differs),
        "chain_windows": {
            "total": windows,
            "native_already_deepest_first": ordered,
            "depth_inverted": inverted,
            "non_monotone": non_monotone,
            "depth_inverted_and_touched": inverted_touched_windows,
        },
        "decisions_with_reachable_depth_inversion": decisions_with_reachable_inversion,
        "decisions_with_reachable_depth_inversion_scorable": (
            decisions_with_reachable_inversion_scorable
        ),
        "q_vs_rank": {
            "comparable_decisions": len(q_compared),
            "agrees": sum(1 for row in q_compared if row.q_order_agrees_with_rank),
            "disagrees": sum(1 for row in q_compared if not row.q_order_agrees_with_rank),
        },
        "expected_loss_delta": {
            "mean": statistics.fmean(delta) if delta else None,
            "min": min(delta) if delta else None,
            "max": max(delta) if delta else None,
            "non_zero_decisions": sum(1 for value in delta if value != 0),
        },
        "is_physical_benefit": False,
    }


def examples(
    geometries: Sequence[tuple[DecisionDivergence, DecisionGeometry]],
) -> dict[str, object]:
    """One improving case and one non-improving case, if either exists."""
    differs = [
        pair for pair in geometries if pair[0].victim_set_differs and pair[0].scorable
    ]
    positive = next(
        (
            pair
            for pair in differs
            if pair[0].cost_aware.expected_recompute < pair[0].native.expected_recompute
        ),
        None,
    )
    negative = next(
        (
            pair
            for pair in differs
            if pair[0].cost_aware.expected_recompute >= pair[0].native.expected_recompute
        ),
        None,
    )
    return {
        "positive": _shape(positive[0]) if positive else None,
        "non_positive": _shape(negative[0]) if negative else None,
    }


def run(artifact_root: Path, *, tau_seconds: float = 30.0) -> dict[str, object]:
    """Analyse every run under ``artifact_root`` with the corrected geometry."""
    run_dirs = sorted({path.parent for path in artifact_root.rglob("events.jsonl")})
    pairs: list[tuple[DecisionDivergence, DecisionGeometry]] = []
    failures: list[dict[str, str]] = []
    for run_dir in run_dirs:
        try:
            decisions = decisions_for_run(run_dir)
        except (FileNotFoundError, KeyError, ValueError) as error:
            failures.append(
                {"run": run_dir.name, "error": f"{type(error).__name__}: {error}"}
            )
            continue
        for decision in decisions:
            geometry = build_geometry(decision, need=0, tau_seconds=tau_seconds)
            if not geometry.blocks:
                continue
            need = min(decision.snapshot.target, len(geometry.blocks))
            row = evaluate(
                run_id=decision.snapshot.run_id,
                decision_event_index=decision.snapshot.decision_event_index,
                geometry=geometry,
                need=need,
            )
            pairs.append((row, geometry))

    return {
        "schema_version": "phase2g.a2_mechanism.v2",
        "tau_seconds": tau_seconds,
        "corpus": str(artifact_root),
        "runs_analysed": len(run_dirs) - len(failures),
        "run_failures": failures,
        "summary": summarise(pairs),
        "examples": examples(pairs),
        "is_physical_benefit": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--tau", type=float, default=30.0)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    if not args.corpus.is_dir():
        print(f"NOT_COMPUTABLE: corpus not found: {args.corpus}", file=sys.stderr)
        return 2

    result = run(args.corpus, tau_seconds=args.tau)
    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text, encoding="utf-8")
        print(f"wrote A2 mechanism study: {args.json}")
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
