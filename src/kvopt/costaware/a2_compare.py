"""A2 study driver: native LRU versus cost-aware block selection on real decisions.

Runs against a Phase 2A / 2G artifact root, reconstructs block geometry, and
reports how often the two rules diverge and what the expected-loss difference is.
Selection-level evidence only: no block is actually evicted and no token count is
measured here.

Usage::

    python -m kvopt.costaware.a2_compare --corpus <artifact-root> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .a2_mechanism import DecisionDivergence, analyse_decision
from .replay import candidate_key, load_decision_snapshots


def _load(artifact_root: Path, *, formal: bool) -> tuple[list, dict]:
    from kvopt.profiling.pipeline import (
        build_derived_dataset_bundle,
        discover_run_artifacts,
    )

    raw_runs = discover_run_artifacts(artifact_root)
    bundle = build_derived_dataset_bundle(raw_runs, formal_campaign=formal)
    snapshots = load_decision_snapshots(raw_runs)
    rows_by_decision: dict[tuple[str, int], dict] = {}
    for row in bundle.decision_candidates:
        rows_by_decision.setdefault((row.run_id, row.decision_event_index), {})[
            candidate_key(row)
        ] = row
    return snapshots, rows_by_decision


def summarise(divergences: Sequence[DecisionDivergence]) -> dict[str, object]:
    total = len(divergences)
    order_differs = [d for d in divergences if d.order_differs]
    set_differs = [d for d in divergences if d.set_differs]
    better = [d for d in divergences if d.cost_aware.expected_recompute < d.native.expected_recompute]
    worse = [d for d in divergences if d.cost_aware.expected_recompute > d.native.expected_recompute]
    tied = [
        d for d in divergences if d.cost_aware.expected_recompute == d.native.expected_recompute
    ]
    deltas = [
        d.cost_aware.expected_recompute - d.native.expected_recompute for d in divergences
    ]
    multi_chain = [d for d in divergences if d.chain_count >= 2]
    return {
        "decisions": total,
        "decisions_with_two_or_more_chains": len(multi_chain),
        "order_differs": len(order_differs),
        "set_differs": len(set_differs),
        "order_differs_without_set_change": len(order_differs) - len(set_differs),
        "cost_aware_lower_expected_loss": len(better),
        "cost_aware_higher_expected_loss": len(worse),
        "expected_loss_tied": len(tied),
        "mean_expected_loss_delta": statistics.fmean(deltas) if deltas else None,
        "median_expected_loss_delta": statistics.median(deltas) if deltas else None,
        "chains_touched_counts": dict(
            Counter(len(d.cost_aware.chains_touched) for d in divergences)
        ),
        "is_physical_benefit": False,
    }


def _examples(
    divergences: Sequence[DecisionDivergence],
) -> dict[str, object]:
    """One positive example and one degenerate/worse example, if they exist."""
    positive = next(
        (
            d
            for d in divergences
            if d.set_differs
            and d.cost_aware.expected_recompute < d.native.expected_recompute
        ),
        None,
    )
    negative = next(
        (
            d
            for d in divergences
            if d.set_differs
            and d.cost_aware.expected_recompute >= d.native.expected_recompute
        ),
        None,
    )

    def _shape(row: DecisionDivergence | None) -> dict[str, object] | None:
        if row is None:
            return None
        return {
            "run_id": row.run_id,
            "decision_event_index": row.decision_event_index,
            "target_blocks": row.target,
            "legal_blocks": row.legal_count,
            "chain_count": row.chain_count,
            "native": asdict(row.native),
            "cost_aware": asdict(row.cost_aware),
        }

    return {"positive": _shape(positive), "non_positive": _shape(negative)}


def run(artifact_root: Path, *, formal: bool = False, tau: float = 30.0) -> dict[str, object]:
    snapshots, rows_by_decision = _load(artifact_root, formal=formal)
    divergences: list[DecisionDivergence] = []
    skipped = 0
    for snapshot in snapshots:
        rows = rows_by_decision.get((snapshot.run_id, snapshot.decision_event_index))
        if not rows:
            skipped += 1
            continue
        analysis = analyse_decision(snapshot, rows, tau_seconds=tau)
        if analysis is None:
            skipped += 1
            continue
        divergences.append(analysis)

    return {
        "schema_version": "phase2g.a2_mechanism.v1",
        "tau_seconds": tau,
        "skipped_decisions": skipped,
        "summary": summarise(divergences),
        "examples": _examples(divergences),
        "unowned_legal_blocks_present": sum(
            1
            for d in divergences
            if any(branch == "unowned_first" for branch in (d.branch,))
        ),
        "is_physical_benefit": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--formal", action="store_true")
    parser.add_argument("--tau", type=float, default=30.0)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    if not args.corpus.is_dir():
        print(f"NOT_COMPUTABLE: corpus not found: {args.corpus}", file=sys.stderr)
        return 2

    result = run(args.corpus, formal=args.formal, tau=args.tau)
    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text, encoding="utf-8")
        print(f"wrote A2 mechanism study: {args.json}")
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
