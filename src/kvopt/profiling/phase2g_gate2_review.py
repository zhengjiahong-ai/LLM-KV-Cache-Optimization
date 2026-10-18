"""Phase 2G Gate 2 review: the three checks M1 asked for, in one run.

Run against the Gate 2 artifact root::

    python -m kvopt.profiling.phase2g_gate2_review \
        --manifest <campaign-manifest.json> \
        --run-root <runs-dir> \
        --output <review.json>

The three checks are deliberately separate, because they establish different
things and fail for different reasons:

1. **Token metric consistency** -- is the paired delta under the frozen
   recomputation metric ``E - C`` the same as under actual prefill ``N - C``?
   Answered per pair, not globally, since the equivalence condition is per request.
2. **Physical evidence attribution** -- how many native evictions map to a unique
   content identity, and among selection-divergence pairs how many also show
   physical divergence. Unmapped evictions lower the evidence level rather than
   invalidating the pairing.
3. **Request completeness** -- are both arms' eligible populations identical? A
   silent omission in one arm would undercount that arm only.

Nothing here re-runs native work and nothing writes to the repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from .phase2g_a1_bounded_gate import evaluate_campaign


def _metric_section(report: dict[str, object]) -> dict[str, object]:
    pairs = report["pairs"]
    comparable = [row for row in pairs if row.get("status") == "COMPARABLE"]
    equivalence = Counter(str(row.get("metric_equivalence")) for row in pairs)

    deltas_r = [
        int(row["token_delta_a1_minus_a0"])
        for row in comparable
        if row.get("token_delta_a1_minus_a0") is not None
    ]
    deltas_w = [
        int(row["delta_actual_prefill_a1_minus_a0"])
        for row in comparable
        if row.get("delta_actual_prefill_a1_minus_a0") is not None
    ]
    differences = [
        int(row["delta_difference_actual_prefill_minus_recomputed"])
        for row in comparable
        if row.get("delta_difference_actual_prefill_minus_recomputed") is not None
    ]

    return {
        "check": "TOKEN_METRIC_CONSISTENCY",
        "frozen_definitions": {
            "actual_prefill_tokens": "N - C",
            "recomputed_tokens": "E - C",
            "new_suffix_tokens": "N - E",
        },
        "gate2_previous_implementation": (
            "computed N - C and reported it as both aggregate_recomputed_tokens "
            "and aggregate_actual_prefill_tokens"
        ),
        "equivalence_counts": dict(sorted(equivalence.items())),
        "all_pairs_equivalent": (
            set(equivalence) == {"EXACT"} if equivalence else None
        ),
        "comparable_pair_count": len(comparable),
        "sum_delta_recomputed_tokens": sum(deltas_r) if deltas_r else None,
        "sum_delta_actual_prefill_tokens": sum(deltas_w) if deltas_w else None,
        "max_abs_delta_difference": max((abs(value) for value in differences), default=None),
        "deltas_identical_for_every_pair": (
            all(value == 0 for value in differences) if differences else None
        ),
        "conclusion": (
            "EQUIVALENT_FOR_PAIRED_DELTAS"
            if differences and all(value == 0 for value in differences)
            else "NOT_EQUIVALENT_USE_FROZEN_METRIC"
            if differences
            else "NOT_COMPUTABLE"
        ),
    }


def _physical_section(report: dict[str, object]) -> dict[str, object]:
    runs = report["runs"]
    pairs = report["pairs"]
    comparable = [row for row in pairs if row.get("status") == "COMPARABLE"]
    divergent = [row for row in comparable if row.get("selection_diverged")]

    unmapped = sum(int(row.get("unmapped_physical_eviction_count") or 0) for row in runs)
    evictions = sum(int(row.get("physical_eviction_count") or 0) for row in runs)
    return {
        "check": "PHYSICAL_EVIDENCE_ATTRIBUTION",
        "total_native_evictions": evictions,
        "unmapped_native_evictions": unmapped,
        "mapped_fraction": (
            None if evictions == 0 else round(1.0 - unmapped / evictions, 6)
        ),
        "selection_divergent_pairs": len(divergent),
        "selection_divergent_pairs_with_physical_divergence": sum(
            bool(row.get("physical_diverged")) for row in divergent
        ),
        "evidence_levels": {
            "logical_release": "confirmed by FORCED_RELEASE_DECISION selections",
            "physical_content": (
                "confirmed only for evictions whose cache key maps to exactly one "
                "recorded block hash; unmapped evictions are observational gaps"
            ),
            "eviction_to_recomputation_causality": (
                "NOT established per eviction; the paired token delta is a "
                "strategy-level measurement, not a per-event attribution"
            ),
        },
    }


def _completeness_section(report: dict[str, object]) -> dict[str, object]:
    pairs = report["pairs"]
    counts = Counter(str(row.get("request_completeness")) for row in pairs)
    incomplete = [
        {
            "scenario_id": row.get("scenario_id"),
            "repeat": row.get("repeat"),
            "unpaired_request_ids": row.get("unpaired_request_ids"),
        }
        for row in pairs
        if row.get("request_completeness") == "UNPAIRED"
    ]
    return {
        "check": "REQUEST_COMPLETENESS",
        "completeness_counts": dict(sorted(counts.items())),
        "incomplete_pairs": incomplete,
        "conclusion": (
            "COMPLETE" if set(counts) == {"COMPLETE"} else "INCOMPLETE_OR_UNKNOWN"
        ),
    }


def review(*, manifest_path: Path, run_root: Path) -> dict[str, object]:
    if not manifest_path.is_file():
        raise FileNotFoundError(f"campaign manifest not found: {manifest_path}")
    if not run_root.is_dir():
        raise FileNotFoundError(f"run root not found: {run_root}")

    report = evaluate_campaign(manifest_path=manifest_path, run_root=run_root)
    overview = report["overall"]
    return {
        "schema_version": "phase2g.a1_gate2_review.v1",
        "overall": overview,
        "direction_counts": overview.get("better_worse_tied_inconclusive"),
        "metric": _metric_section(report),
        "physical": _physical_section(report),
        "completeness": _completeness_section(report),
        "supporting_report": {
            "run_status_counts": report["run_status_counts"],
            "pair_status_counts": report["pair_status_counts"],
            "evidence_state_counts": report["evidence_state_counts"],
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        result = review(manifest_path=args.manifest, run_root=args.run_root)
    except FileNotFoundError as error:
        print(f"NOT_COMPUTABLE: {error}", file=sys.stderr)
        return 2

    text = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote Phase 2G Gate 2 review: {args.output}")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
