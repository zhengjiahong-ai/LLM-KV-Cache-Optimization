"""Read-only reproduction of the Phase 3 null-mechanism analysis.

Recomputes the four decisive checks reported in
``docs/experiments/phase3-algorithm-null-mechanism-analysis.md`` from the frozen
evidence archive. Touches no Protocol input, writes nothing outside ``--out``,
and never issues a GPU command.

Usage
-----
    python scripts/probes/phase3_null_mechanism/probe.py \
        --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
        --audit docs/experiments/phase3-algorithm-exposure-audit-data \
        --out local/phase3-null-mechanism-probe

What it checks
--------------
A. per-request arm equivalence: A0 vs A1/A2/A3/E0 on ``recomputed_tokens`` and
   ``eligible_prefix_tokens`` for every request of every cell.
B. A0 - N0 difference localisation: which request(s) carry a difference.
C. competitive-decision extraction: the ``A3_SUFFIX_RELEASE_DECISION`` audit
   rows, with the per-candidate scoring inputs.
D. eviction accounting: predicted victims vs matched physical blocks.

Every printed number is derived from files on disk. Nothing is assumed.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

#: Block size of the frozen runtime configuration.
BLOCK_SIZE_TOKENS = 16

#: Arms compared against A0 in check A.
COMPARED_ARMS = ("A1", "A2", "A3", "E0")


@dataclass(slots=True)
class PerRequestResult:
    observations: int = 0
    comparisons: int = 0
    mismatches: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class A0N0Result:
    cells_with_difference: int = 0
    cells_total: int = 0
    difference_always_last_request: int = 0
    per_cell: list[dict] = field(default_factory=list)
    total_tokens: int = 0


def _load_cell_reports(nec_dir: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(nec_dir.glob("*.json"))]


def check_per_request_equivalence(cells: list[dict]) -> PerRequestResult:
    """A0 vs each compared arm, per request, on two independent fields."""

    result = PerRequestResult()
    for cell in cells:
        a0 = {r["request_id"]: r for r in cell["arms"]["A0"]["requests"]}
        for arm in COMPARED_ARMS:
            for row in cell["arms"][arm]["requests"]:
                result.observations += 1
                base = a0.get(row["request_id"])
                result.comparisons += 1
                if base is None:
                    result.mismatches.append(
                        {
                            "group": cell["group_id"],
                            "condition": cell["condition"],
                            "arm": arm,
                            "request": row["request_id"],
                            "reason": "request_missing_in_A0",
                        }
                    )
                    continue
                for fld in ("recomputed_tokens", "eligible_prefix_tokens"):
                    if row[fld] != base[fld]:
                        result.mismatches.append(
                            {
                                "group": cell["group_id"],
                                "condition": cell["condition"],
                                "arm": arm,
                                "request": row["request_id"],
                                "field": fld,
                                "A0": base[fld],
                                "other": row[fld],
                            }
                        )
    return result


def check_a0_vs_n0(cells: list[dict]) -> A0N0Result:
    """Which request carries the A0 - N0 difference, and how often."""

    result = A0N0Result(cells_total=len(cells))
    for cell in cells:
        order = [r["request_id"] for r in cell["arms"]["A0"]["requests"]]
        a0 = {r["request_id"]: r for r in cell["arms"]["A0"]["requests"]}
        n0 = {r["request_id"]: r for r in cell["arms"]["N0"]["requests"]}
        diffs = [
            rid
            for rid in order
            if rid in n0 and a0[rid]["recomputed_tokens"] != n0[rid]["recomputed_tokens"]
        ]
        if not diffs:
            continue
        result.cells_with_difference += 1
        result.total_tokens += sum(
            a0[rid]["recomputed_tokens"] - n0[rid]["recomputed_tokens"] for rid in diffs
        )
        last = order[-1]
        if diffs == [last]:
            result.difference_always_last_request += 1
        result.per_cell.append(
            {
                "group": cell["group_id"],
                "condition": cell["condition"],
                "differing_requests": diffs,
                "is_exactly_last_request": diffs == [last],
                "delta_tokens": sum(
                    a0[rid]["recomputed_tokens"] - n0[rid]["recomputed_tokens"] for rid in diffs
                ),
            }
        )
    return result


def check_competitive_decisions(evidence: Path) -> list[dict]:
    """Extract the A3 Step-2 audit rows that exposed a competing candidate."""

    rows: list[dict] = []
    for events_path in sorted(evidence.glob("native-runs/*-a3/events.jsonl")):
        run_id = events_path.parent.name
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event_type") != "A3_SUFFIX_RELEASE_DECISION":
                continue
            payload = event.get("payload") or {}
            trace = payload.get("selection_trace") or []
            if not trace:
                continue
            step = trace[0]
            audits = step.get("audits") or []
            rows.append(
                {
                    "run_id": run_id,
                    "decision_id": payload.get("decision_id"),
                    "need": step.get("need"),
                    "deficit": step.get("deficit"),
                    "branch": step.get("a1_branch"),
                    "candidate_count": len(audits),
                    "selected_program": ((step.get("a1_key") or [None])[0]),
                    "candidates": [
                        {
                            "program": (audit.get("key") or ["?"])[0],
                            "selected": audit.get("selected"),
                            "suffix_blocks": audit.get("suffix_blocks"),
                            "chain_length": audit.get("chain_length"),
                            "d_min": audit.get("d_min"),
                            "new_blocks": audit.get("new_blocks"),
                            "prefill_reload_seconds": audit.get("prefill_reload_seconds"),
                            "reuse_proxy": audit.get("reuse_proxy"),
                            "score": audit.get("score"),
                        }
                        for audit in audits
                    ],
                }
            )
    return rows


def check_eviction_accounting(audit_dir: Path) -> dict:
    """Predicted victims vs matched physical blocks, from the audit CSV."""

    csv_path = audit_dir / "decision-audit.csv"
    if not csv_path.is_file():
        return {"status": "AUDIT_CSV_MISSING"}
    rows = [
        row
        for row in csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines())
        if row["arm"] == "A3"
    ]
    matched_eq_need = sum(1 for r in rows if int(r["matched_physical_blocks"]) == int(r["need"]))
    predicted_eq_need = sum(1 for r in rows if int(r["predicted_victim_count"]) == int(r["need"]))
    matched_gt_need = [
        {
            "group": r["group_id"],
            "condition": r["condition"],
            "need": int(r["need"]),
            "matched": int(r["matched_physical_blocks"]),
        }
        for r in rows
        if int(r["matched_physical_blocks"]) != int(r["need"])
    ]
    return {
        "decision_rows": len(rows),
        "matched_physical_blocks_total": sum(int(r["matched_physical_blocks"]) for r in rows),
        "predicted_victim_total": sum(int(r["predicted_victim_count"]) for r in rows),
        "predicted_physical_overlap_total": sum(
            int(r["predicted_physical_overlap_count"]) for r in rows
        ),
        "predicted_victim_count_equals_need": f"{predicted_eq_need}/{len(rows)}",
        "matched_physical_blocks_equals_need": f"{matched_eq_need}/{len(rows)}",
        "rows_where_physical_exceeds_need": matched_gt_need,
        "candidate_count_distribution": dict(
            sorted(Counter(int(r["candidate_count"]) for r in rows).items())
        ),
        "step_distribution": dict(Counter(r["step"] for r in rows)),
        "a3_vs_a1_same_program": dict(Counter(r["a3_vs_a1_same_program"] for r in rows)),
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path(
            "local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2"
        ),
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("docs/experiments/phase3-algorithm-exposure-audit-data"),
    )
    parser.add_argument("--out", type=Path, default=Path("local/phase3-null-mechanism-probe"))
    args = parser.parse_args(argv)

    cells = _load_cell_reports(args.evidence / "nec-cells")
    if not cells:
        raise SystemExit(f"no cell reports under {args.evidence / 'nec-cells'}")

    equivalence = check_per_request_equivalence(cells)
    a0_n0 = check_a0_vs_n0(cells)
    competitive = check_competitive_decisions(args.evidence)
    eviction = check_eviction_accounting(args.audit)

    multi = [row for row in competitive if row["candidate_count"] >= 2]
    suffix_vs_need = Counter(
        "equal"
        if c["suffix_blocks"] == row["need"]
        else ("greater" if c["suffix_blocks"] > row["need"] else "less")
        for row in competitive
        for c in row["candidates"]
    )
    counterfactual_upper_bound = sum(row["need"] for row in multi) * BLOCK_SIZE_TOKENS

    payload = {
        "schema_version": "phase3.null_mechanism_probe.v1",
        "evidence_path": str(args.evidence).replace("\\", "/"),
        "checks": {
            "A_per_request_arm_equivalence": {
                "observations": equivalence.observations,
                "comparisons": equivalence.comparisons,
                "mismatch_count": len(equivalence.mismatches),
                "mismatches": equivalence.mismatches[:20],
            },
            "B_a0_vs_n0_localisation": {
                "cells_total": a0_n0.cells_total,
                "cells_with_difference": a0_n0.cells_with_difference,
                "cells_where_difference_is_exactly_the_last_request": (
                    a0_n0.difference_always_last_request
                ),
                "sum_A0_minus_N0_tokens": a0_n0.total_tokens,
                "per_cell": a0_n0.per_cell,
            },
            "C_competitive_decisions": {
                "a3_decisions": len(competitive),
                "multi_candidate_decisions": len(multi),
                "candidate_count_distribution": dict(
                    sorted(Counter(r["candidate_count"] for r in competitive).items())
                ),
                "step2_sufficient": sum(1 for r in competitive if r["branch"] == "single_step"),
                "suffix_blocks_vs_need": dict(suffix_vs_need),
                "counterfactual_upper_bound_tokens": counterfactual_upper_bound,
                "counterfactual_upper_bound_per_paired_group": round(
                    counterfactual_upper_bound / 18.0, 2
                ),
                "multi_candidate_detail": multi,
            },
            "D_eviction_accounting": eviction,
        },
    }

    args.out.mkdir(parents=True, exist_ok=True)
    _write(args.out / "null-mechanism-probe.json", payload)

    print("== A. per-request arm equivalence ==")
    print(
        f"  observations {equivalence.observations}  comparisons "
        f"{equivalence.comparisons}  mismatches {len(equivalence.mismatches)}"
    )
    print()
    print("== B. A0 - N0 localisation ==")
    print(f"  cells with a difference: {a0_n0.cells_with_difference}/{a0_n0.cells_total}")
    print(
        "  cells where the difference is exactly the last request: "
        f"{a0_n0.difference_always_last_request}/{a0_n0.cells_with_difference}"
    )
    print(f"  sum(A0 - N0) over all cells: {a0_n0.total_tokens} tokens")
    print()
    print("== C. A3 decisions ==")
    print(
        f"  decisions {len(competitive)}  multi-candidate {len(multi)}  "
        f"candidate distribution "
        f"{dict(sorted(Counter(r['candidate_count'] for r in competitive).items()))}"
    )
    print(f"  suffix_blocks vs need: {dict(suffix_vs_need)}")
    print(
        "  counterfactual upper bound (sum need x 16): "
        f"{counterfactual_upper_bound} tokens "
        f"(~{counterfactual_upper_bound / 18.0:.0f} per paired group)"
    )
    print()
    print("== D. eviction accounting ==")
    for key, value in eviction.items():
        if key != "rows_where_physical_exceeds_need":
            print(f"  {key}: {value}")
    print(
        "  rows where physical exceeds need: "
        f"{len(eviction.get('rows_where_physical_exceeds_need', []))}"
    )
    print()
    print(f"== written to {args.out / 'null-mechanism-probe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
