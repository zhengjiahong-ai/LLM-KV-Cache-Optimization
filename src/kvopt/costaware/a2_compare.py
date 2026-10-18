"""A2 block-level mechanism study driver.

Answers, on recorded evidence and with proved content identity:

RQ1  Is there a real block-level selection space? -- measured as *victim-set*
     divergence under a fixed entry release, never as ordering difference, and only
     counted on decisions whose candidates are fully identifiable.
RQ2  Can the difference be explained by decision-time cost information? -- the loss
     comparison is only reported when every block's content and every chain's reuse
     weight are known; otherwise the selection is kept as a diagnostic.
RQ3  Would A2 be worth a native implementation? -- a screening gate plus the
     interface gap that currently blocks it.

Screening gate (not a hard AND of every signal)
-----------------------------------------------
A decision counts toward the gate when all three hold:

1. every candidate is **identified**: content identity and depth proved from a
   snapshot under the ``_mapping_for_candidate`` protocol, and every priced chain has
   a reuse weight;
2. the two rules produce a **nontrivial victim-set difference**;
3. the cost-aware set has a **lower modelled loss**.

Depth inversion and ``q``-versus-rank disagreement are then used to *stratify the
cause* of a divergence, not to gate it. A single chain with inverted depth can
produce a different victim set with no ``q`` comparison at all, so requiring both
would discard exactly the case the study exists to find.

Corpus labelling
----------------
``--corpus-label`` records which corpus a report describes. Gate 2 is reported as
``NOT_COMPUTABLE`` unless its archive is actually supplied, so a legacy-corpus result
can never be presented as the Gate 2 verdict.

Usage::

    python -m kvopt.costaware.a2_compare --corpus <artifact-root> \
        [--corpus-label gate2|legacy|other] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path

from .a2_evidence import DEFAULT_TAU_SECONDS, build_geometry, decisions_for_run
from .a2_geometry import (
    ChainKey,
    DecisionDivergence,
    DecisionGeometry,
    evaluate,
)

#: Values for ``--corpus-label``.
LABEL_GATE2 = "gate2"
LABEL_LEGACY = "legacy"
LABEL_OTHER = "other"

#: Divergence causes, used for stratification only.
CAUSE_DEPTH_INVERSION = "depth_inversion"
CAUSE_Q_REORDER = "q_reorder"
CAUSE_SHARED_OWNERSHIP = "shared_ownership"
CAUSE_UNCLASSIFIED = "unclassified"


def chain_windows(geometry: DecisionGeometry) -> tuple[int, int, int, int]:
    """(native_already_deepest, depth_inverted, non_monotone, total) windows.

    A smaller ``native_lru_rank`` means colder, so it is evicted earlier.

    - rank **decreasing** with depth => deeper blocks are colder => native already
      evicts deepest-first, which is optimal inside the chain;
    - rank **increasing** with depth => shallower blocks are colder => native moves
      the gap inward on its first pick, extending the missing suffix fastest, which is
      the case a depth rule could improve on.

    Both are measured against proved **content depth**, never against rank.
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


def inverted_touched_chains(geometry: DecisionGeometry, victim: Sequence[int]) -> int:
    """Inverted-depth chains that the victim set actually touches."""
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


def divergence_causes(
    row: DecisionDivergence, geometry: DecisionGeometry
) -> tuple[str, ...]:
    """Why the victim sets differ, stratified rather than combined into one flag."""
    if not row.victim_set_differs:
        return ()
    causes: list[str] = []
    if inverted_touched_chains(geometry, row.native_blocks):
        causes.append(CAUSE_DEPTH_INVERSION)
    if row.q_order_agrees_with_rank is False:
        causes.append(CAUSE_Q_REORDER)
    if row.shared_block_count:
        causes.append(CAUSE_SHARED_OWNERSHIP)
    return tuple(causes) or (CAUSE_UNCLASSIFIED,)


def _shape(
    row: DecisionDivergence, geometry: DecisionGeometry
) -> dict[str, object]:
    return {
        "run_id": row.run_id,
        "decision_event_index": row.decision_event_index,
        "need": row.need,
        "legal_count": row.legal_count,
        "chain_count": row.chain_count,
        "shared_blocks": row.shared_block_count,
        "native_blocks": list(row.native_blocks),
        "cost_aware_blocks": list(row.cost_aware_blocks),
        "victim_set_differs": row.victim_set_differs,
        "verified": row.verified,
        "native_expected_loss": (
            None if row.native is None else row.native.proxy_weighted_loss
        ),
        "cost_aware_expected_loss": (
            None if row.cost_aware is None else row.cost_aware.proxy_weighted_loss
        ),
        "expected_loss_delta": (
            None
            if row.native is None or row.cost_aware is None
            else row.cost_aware.proxy_weighted_loss - row.native.proxy_weighted_loss
        ),
        "q_order_agrees_with_rank": row.q_order_agrees_with_rank,
        "causes": list(divergence_causes(row, geometry)),
        "unknown_weight_chains": list(row.unknown_weight_chains),
        "gap_count": len(row.gaps),
    }


def summarise(
    geometries: Sequence[tuple[DecisionDivergence, DecisionGeometry]],
) -> dict[str, object]:
    """Aggregate with strict filtering, then recompute denominators.

    Nothing is silently dropped: every exclusion is counted under ``exclusions`` so a
    reader can reconstruct the published denominators.
    """
    total = len(geometries)
    verified = [pair for pair in geometries if pair[0].verified]
    differs = [pair for pair in geometries if pair[0].victim_set_differs]
    verified_differs = [pair for pair in verified if pair[0].victim_set_differs]

    exclusions: Counter[str] = Counter()
    for row, geometry in geometries:
        if row.verified:
            continue
        if geometry.gaps:
            exclusions["content_unverified"] += 1
        if geometry.unknown_weight_chains:
            exclusions["reuse_weight_unknown"] += 1
        if not geometry.gaps and not geometry.unknown_weight_chains:
            exclusions["cost_not_computable"] += 1

    freedom = [pair for pair in verified if pair[0].legal_count > pair[0].need]
    delta = [
        pair[0].cost_aware.proxy_weighted_loss - pair[0].native.proxy_weighted_loss
        for pair in verified
        if pair[0].native is not None and pair[0].cost_aware is not None
    ]
    improving = [pair for pair in verified_differs if _delta(pair[0]) is not None and _delta(pair[0]) < 0]

    causes = Counter(
        cause for pair in verified_differs for cause in divergence_causes(*pair)
    )

    ordered = inverted = non_monotone = windows = 0
    for _, geometry in geometries:
        o, i, n, t = chain_windows(geometry)
        ordered += o
        inverted += i
        non_monotone += n
        windows += t

    q_compared = [
        pair[0] for pair in geometries if pair[0].q_order_agrees_with_rank is not None
    ]

    return {
        "decisions": total,
        # ---- strict denominators ----
        "verified_decisions": len(verified),
        "excluded_decisions": total - len(verified),
        "exclusions": dict(sorted(exclusions.items())),
        "verified_decisions_with_freedom": len(freedom),
        # ---- the screening gate: identified + set differs + lower loss ----
        "screening_gate": {
            "criteria": [
                "fully identified candidates",
                "nontrivial victim-set difference",
                "lower modelled loss under the cost-aware rule",
            ],
            "qualifying_decisions": len(improving),
            "denominator_verified_decisions": len(verified),
            "passed": bool(improving),
        },
        # ---- diagnostics, computed on every decision, never a verdict ----
        "diagnostic": {
            "order_differs": sum(1 for pair in geometries if pair[0].order_differs),
            "victim_set_differs": len(differs),
            "victim_set_differs_verified": len(verified_differs),
            "victim_set_differs_unverified": len(differs) - len(verified_differs),
            "divergence_causes_verified": dict(sorted(causes.items())),
        },
        "multi_chain_decisions": sum(1 for pair in geometries if pair[0].chain_count >= 2),
        "shared_blocks_seen": sum(pair[0].shared_block_count for pair in geometries),
        "chain_windows": {
            "total": windows,
            "native_already_deepest_first": ordered,
            "depth_inverted": inverted,
            "non_monotone": non_monotone,
        },
        "q_vs_rank": {
            "comparable_decisions": len(q_compared),
            "agrees": sum(1 for row in q_compared if row.q_order_agrees_with_rank),
            "disagrees": sum(1 for row in q_compared if not row.q_order_agrees_with_rank),
        },
        "expected_loss_delta_verified": {
            "mean": statistics.fmean(delta) if delta else None,
            "min": min(delta) if delta else None,
            "max": max(delta) if delta else None,
            "non_zero_decisions": sum(1 for value in delta if value != 0),
            "units": "proxy-weighted block units, block size factored out",
            "tau_frozen": True,
        },
        "is_physical_benefit": False,
    }


def _delta(row: DecisionDivergence) -> float | None:
    if row.native is None or row.cost_aware is None:
        return None
    return row.cost_aware.proxy_weighted_loss - row.native.proxy_weighted_loss


def examples(
    geometries: Sequence[tuple[DecisionDivergence, DecisionGeometry]],
) -> dict[str, object]:
    """One improving case and one non-improving case, verified decisions only."""
    differs = [
        pair for pair in geometries if pair[0].verified and pair[0].victim_set_differs
    ]
    positive = next((pair for pair in differs if (_delta(pair[0]) or 0.0) < 0), None)
    negative = next((pair for pair in differs if (_delta(pair[0]) or 0.0) >= 0), None)
    return {
        "positive": _shape(*positive) if positive else None,
        "non_positive": _shape(*negative) if negative else None,
        "any_unverified_differs": next(
            (
                _shape(*pair)
                for pair in geometries
                if pair[0].victim_set_differs and not pair[0].verified
            ),
            None,
        ),
    }


def gate2_status(artifact_root: Path | None, label: str) -> dict[str, object]:
    """State plainly whether this report is a Gate 2 verdict or cannot be one."""
    if label == LABEL_GATE2 and artifact_root is not None:
        return {
            "corpus": LABEL_GATE2,
            "computable": True,
            "reason": "Gate 2 archive supplied by the caller",
        }
    if label == LABEL_GATE2:
        return {
            "corpus": LABEL_GATE2,
            "computable": False,
            "reason": "no Gate 2 archive supplied",
        }
    return {
        "corpus": label if label else "unspecified",
        "computable": False,
        "reason": (
            "this is not the Gate 2 corpus; its result must not be reported as the "
            "Gate 2 verdict"
        ),
    }


def run(
    artifact_root: Path,
    *,
    tau_seconds: float = DEFAULT_TAU_SECONDS,
    corpus_label: str = "",
) -> dict[str, object]:
    """Analyse every run under ``artifact_root``."""
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
        "schema_version": "phase2g.a2_mechanism.v3",
        "tau_seconds": tau_seconds,
        "corpus": str(artifact_root),
        "corpus_label": corpus_label or "unspecified",
        "gate2": gate2_status(None, corpus_label),
        "runs_analysed": len(run_dirs) - len(failures),
        "run_failures": failures,
        "summary": summarise(pairs),
        "examples": examples(pairs),
        "identity_protocol": {
            "method": "latest prior snapshot + ordered block_ids equality + "
            "intervening eviction check (phase2d_shared_retention protocol)",
            "depth_source": "position in proved chain content, never native rank",
            "unknown_handling": "unproved content or missing reuse weight makes the "
            "decision unscorable; it is never scored as zero",
        },
        "is_physical_benefit": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--tau", type=float, default=DEFAULT_TAU_SECONDS)
    parser.add_argument(
        "--corpus-label",
        choices=[LABEL_GATE2, LABEL_LEGACY, LABEL_OTHER],
        default="",
        help="record which corpus this report describes",
    )
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    if not args.corpus.is_dir():
        print(f"NOT_COMPUTABLE: corpus not found: {args.corpus}", file=sys.stderr)
        return 2

    result = run(
        args.corpus, tau_seconds=args.tau, corpus_label=args.corpus_label
    )
    if args.corpus_label == LABEL_GATE2:
        result["gate2"] = gate2_status(args.corpus, LABEL_GATE2)

    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text, encoding="utf-8")
        print(f"wrote A2 mechanism study: {args.json}")
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
