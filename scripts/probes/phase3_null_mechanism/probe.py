"""Read-only, fail-closed reproduction of the Phase 3 null-mechanism analysis.

Recomputes the checks reported in
``docs/experiments/phase3-algorithm-null-mechanism-analysis.md`` from the frozen
evidence archive. Touches no Protocol input, writes nothing outside ``--out``,
and never issues a GPU command.

The probe is deliberately fail-closed:

* every request row must exist for every arm, with a unique and identical
  ``request_id`` set across arms;
* every A3 decision must have exactly one selection trace, a complete audit
  list, one selected candidate, and a selected program that equals the
  independently recomputed argmin of the A3 key;
* A1, A0 and E0 selections are recomputed independently from the same
  candidate set (A1 from its own trace; A0/E0 from the A3 deadlines);
* every arithmetic identity and every frozen headline number used by the
  analysis document is checked; a mismatch exits non-zero.

Usage
-----
    python scripts/probes/phase3_null_mechanism/probe.py \
        --evidence local/phase3-option-f-unified-270-runs-v2-evidence/phase3-option-f-unified-270-runs-v2 \
        --audit    docs/experiments/phase3-algorithm-exposure-audit-data \
        --out      local/phase3-null-mechanism-probe
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Block size of the frozen runtime configuration.
BLOCK_SIZE_TOKENS = 16

#: All six arms in every cell.
ARMS = ("A0", "A1", "A2", "A3", "E0", "N0")

#: Arms compared against A0 in the per-request equivalence check.
COMPARED_ARMS = ("A1", "A2", "A3", "E0")

#: Arms that emit a forced-release decision row.
RELEASE_ARMS = ("A0", "A1", "A2", "A3", "E0")

#: Default reuse-proxy time scale (matches ``default_tau_seconds``).
TAU_SECONDS = 30.0

#: Default A1 lambda (matches the frozen arm).
LAMBDA = 0.5

#: SHA-256 of the immutable evidence archive named in the analysis header.
FROZEN_ARCHIVE_SHA256 = "d36a3765296199806e1aef04dcc655fd16d3afb6d7a5bc5a125397bea90ce5c8"

#: Primary paired groups: all Workload Groups except g09 and g18.
NON_PRIMARY_GROUPS = frozenset({"g09", "g18"})

#: H3-0 excludes the C1 cell of the two single-cell groups.
H3_EXCLUDED_CELLS = frozenset({"g09-c1", "g18-c1"})

#: Headline numbers the analysis document claims; all are re-derived.
EXPECTED: dict[str, Any] = {
    "cells": 40,
    "groups": 20,
    "requests_per_arm": 24,
    "request_rows": 5760,
    "comparisons": 3840,
    "request_set_mismatches": 0,
    "a0n0_diff_cells": 20,
    "a0n0_last_request_cells": 20,
    "a0n0_total_tokens": -100352,
    "h30_cells": 38,
    "h30_diff_cells": 18,
    "h30_cell_sum_tokens": -96992,
    "h30_group_sum_tokens": -62464,
    "h30_zero_groups": 6,
    "h30_top5_share_pct": 79.6,
    "h30_a0_group_mean_tokens": 40205.6,
    "all_a0_per_cell_mean_tokens": 39603.6,
    "h30_over_a0_pct": 7.8,
    "a3_decisions": 127,
    "a3_cells": 39,
    "a3_candidates": 134,
    "a3_single_candidate": 120,
    "a3_multi_candidate": 7,
    "suffix_equal": 122,
    "suffix_greater": 12,
    "suffix_less": 0,
    "new_blocks_ge_need": 134,
    "step2_sufficient": 127,
    "predicted_victim_total": 12545,
    "predicted_overlap_total": 12545,
    "matched_physical_total": 14241,
    "predicted_eq_need": 127,
    "matched_eq_need": 108,
    "physical_exceeds_need": 19,
    "required_eq_128": 108,
    "predicted_flag_true": 108,
    "predicted_flag_consistent": 127,
    "a3_recompute_ok": 127,
    "a1_recompute_ok": 127,
    "a0_deadline_ok": 127,
    "e0_deadline_ok": 127,
    "same_program_all": 127,
    "zero_decision_diff_cells": 1,
    "g18_c1_delta": -544,
    "need_127": 52,
    "need_128": 24,
    "need_le_115": 51,
    "cells_with_4096_delta": 8,
    "decision_cells_distribution": {1: 3, 2: 18, 3: 4, 4: 4, 5: 6, 7: 2, 8: 2},
    "noise_cells": 10,
    "noise_groups": 5,
    "noise_runs": 30,
    "noise_df": 20,
    "primary_groups": 18,
    "primary_cells": 36,
    "h3r_groups": 9,
    "h3r_cells": 16,
    "a2_cost_known": 53,
    "a2_fallback": 74,
    "a2_truncated": 51,
    "a2_differs_native": 0,
}


@dataclass
class Check:
    """Accumulates one named check and its failures."""

    name: str
    ok: bool = True
    detail: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def require(self, condition: bool, message: str) -> bool:
        if not condition:
            self.ok = False
            self.failures.append(message)
        return condition

    def expect(self, actual: Any, expected: Any, label: str, *, tol: float = 0.0) -> bool:
        if isinstance(expected, float) or isinstance(actual, float):
            good = math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=tol or 1e-9)
        else:
            good = actual == expected
        return self.require(good, f"{label}: expected {expected!r}, got {actual!r}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)


class Probe:
    """Collects checks; any failed check makes the whole probe FAIL."""

    def __init__(self) -> None:
        self.checks: list[Check] = []

    def check(self, name: str) -> Check:
        item = Check(name)
        self.checks.append(item)
        return item

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.checks)

    def failures(self) -> list[str]:
        out: list[str] = []
        for item in self.checks:
            for failure in item.failures:
                out.append(f"[{item.name}] {failure}")
        return out

    def warnings(self) -> list[str]:
        out: list[str] = []
        for item in self.checks:
            for warning in item.warnings:
                out.append(f"[{item.name}] {warning}")
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            item.name: {
                "ok": item.ok,
                "detail": item.detail,
                "failures": item.failures,
                "warnings": item.warnings,
            }
            for item in self.checks
        }


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def stable_sigmoid(z: float) -> float:
    """Numerically stable logistic function."""
    if z >= 0.0:
        return 1.0 / (1.0 + math.exp(-z))
    exp_z = math.exp(z)
    return exp_z / (1.0 + exp_z)


def reuse_proxy(deadline: float, timestamp: float, tau: float = TAU_SECONDS) -> float:
    return stable_sigmoid((deadline - timestamp) / tau)


def key_tuple(value: Any) -> tuple:
    return tuple(value) if isinstance(value, (list, tuple)) else (value,)


def selected_program(row: dict[str, str]) -> str | None:
    raw = row.get("selected_programs") or ""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], str):
        return parsed[0]
    return None


def step2_sufficient(need: int, audits: list[dict]) -> bool:
    """Step-2 branch predicate: ``new_blocks >= need`` (N), never ``suffix_blocks`` (S)."""
    return need > 0 and any(audit["new_blocks"] >= need for audit in audits)


def pct(part: float, whole: float) -> float:
    return 100.0 * part / whole if whole else 0.0


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_int(value: str | None, label: str) -> int:
    if value is None or value == "":
        raise ValueError(f"missing integer field: {label}")
    return int(value)


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


# ---------------------------------------------------------------------------
# loaders
# ---------------------------------------------------------------------------


def load_cells(check: Check, evidence: Path) -> dict[str, dict]:
    nec_dir = evidence / "nec-cells"
    check.require(nec_dir.is_dir(), f"missing directory: {nec_dir}")
    paths = sorted(nec_dir.glob("*.json"))
    check.expect(len(paths), EXPECTED["cells"], "cell file count")
    cells: dict[str, dict] = {}
    for path in paths:
        cell = load_json(path)
        name = path.stem
        check.require(
            name == f"{cell.get('group_id')}-{cell.get('condition')}".lower(),
            f"{name}: group/condition does not match filename",
        )
        check.require(set(cell.get("arms", {})) == set(ARMS), f"{name}: arm set is not {ARMS}")
        cells[name] = cell
    check.expect(len(cells), EXPECTED["cells"], "loaded cells")
    groups = defaultdict(set)
    for name, cell in cells.items():
        groups[cell["group_id"]].add(cell["condition"])
    check.expect(len(groups), EXPECTED["groups"], "group count")
    for group, conditions in groups.items():
        check.require(conditions == {"C1", "C2"}, f"{group}: conditions are {sorted(conditions)}")
    check.detail["cells"] = len(cells)
    check.detail["groups"] = len(groups)
    return cells


def load_decisions(check: Check, evidence: Path) -> list[dict]:
    """Parse every A3 decision; one entry per A3_SUFFIX_RELEASE_DECISION."""
    decisions: list[dict] = []
    a3_paths = sorted(evidence.glob("native-runs/*-a3/events.jsonl"))
    check.expect(len(a3_paths), EXPECTED["cells"], "A3 run count")
    for path in a3_paths:
        run = path.parent.name
        cell = run.replace("phase3-main-", "").replace("-r1-a3", "")
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        forced = [e for e in events if e.get("event_type") == "FORCED_RELEASE_DECISION"]
        suffix = [e for e in events if e.get("event_type") == "A3_SUFFIX_RELEASE_DECISION"]
        check.require(
            len(suffix) == len(forced),
            f"{cell}: A3 decisions {len(suffix)} != forced-release decisions {len(forced)}",
        )
        for event in suffix:
            payload = event.get("payload") or {}
            decision_id = payload.get("decision_id")
            check.require(bool(decision_id), f"{cell}: A3 decision without decision_id")
            trace = payload.get("selection_trace") or []
            check.require(
                len(trace) == 1, f"{cell}/{decision_id}: selection_trace length {len(trace)} != 1"
            )
            step = trace[0] if trace else {}
            audits = step.get("audits") or []
            check.require(bool(audits), f"{cell}/{decision_id}: empty audit list")
            decisions.append(
                {
                    "run": run,
                    "cell": cell,
                    "decision_id": decision_id,
                    "timestamp": event.get("timestamp"),
                    "forced_event_index": payload.get("decision_event_index"),
                    "need": step.get("need"),
                    "deficit": step.get("deficit"),
                    "branch": step.get("a1_branch"),
                    "selected_key": step.get("a1_key"),
                    "audits": audits,
                    "events": events,
                    "event_index": event.get("event_index"),
                }
            )
    check.expect(len(decisions), EXPECTED["a3_decisions"], "A3 decision count")
    check.detail["a3_decisions"] = len(decisions)
    check.detail["a3_cells"] = len({d["cell"] for d in decisions})
    check.expect(
        len({d["cell"] for d in decisions}), EXPECTED["a3_cells"], "A3 decision cell count"
    )
    return decisions


def load_csv_rows(check: Check, audit: Path) -> list[dict[str, str]]:
    path = audit / "decision-audit.csv"
    check.require(path.is_file(), f"missing audit CSV: {path}")
    rows = read_csv(path)
    check.detail["csv_rows"] = len(rows)
    check.expect(
        len(rows), EXPECTED["a3_decisions"] * len(RELEASE_ARMS), "decision-audit row count"
    )
    counts = Counter(row["arm"] for row in rows)
    check.detail["arm_rows"] = dict(sorted(counts.items()))
    for arm in RELEASE_ARMS:
        check.expect(counts[arm], EXPECTED["a3_decisions"], f"{arm} audit rows")
    return rows


# ---------------------------------------------------------------------------
# A. request-set completeness and per-request equivalence
# ---------------------------------------------------------------------------


def check_request_integrity(check: Check, cells: dict[str, dict]) -> dict[str, Any]:
    request_rows = 0
    observations = 0
    comparisons = 0
    mismatches = 0
    set_mismatches = 0
    arithmetic_failures = 0
    e_mismatches = 0

    for name, cell in cells.items():
        arms = cell["arms"]
        base_ids = [r["request_id"] for r in arms["A0"]["requests"]]
        check.expect(len(base_ids), EXPECTED["requests_per_arm"], f"{name}: A0 request count")
        check.require(len(base_ids) == len(set(base_ids)), f"{name}: duplicate request_id in A0")
        for arm in ARMS:
            requests = arms[arm]["requests"]
            ids = [r["request_id"] for r in requests]
            request_rows += len(requests)
            check.expect(
                len(requests), EXPECTED["requests_per_arm"], f"{name}/{arm}: request count"
            )
            check.require(len(ids) == len(set(ids)), f"{name}/{arm}: duplicate request_id")
            if ids != base_ids:
                set_mismatches += 1
                check.require(False, f"{name}/{arm}: request_id list differs from A0")
            for row in requests:
                expected_recomputed = (
                    row["eligible_prefix_tokens"] - row["native_cached_prefix_tokens"]
                )
                if row["recomputed_tokens"] != expected_recomputed:
                    arithmetic_failures += 1
                    check.require(False, f"{name}/{arm}/{row['request_id']}: recomputed != E - C")
                if not (
                    0
                    <= row["native_cached_prefix_tokens"]
                    <= row["eligible_prefix_tokens"]
                    <= row["native_prompt_tokens"]
                ):
                    arithmetic_failures += 1
                    check.require(False, f"{name}/{arm}/{row['request_id']}: not 0 <= C <= E <= N")
                if (
                    row["actual_prefill_tokens"]
                    != row["new_suffix_tokens"] + row["recomputed_tokens"]
                ):
                    arithmetic_failures += 1
                    check.require(
                        False,
                        f"{name}/{arm}/{row['request_id']}: actual_prefill != new_suffix + recomputed",
                    )
            expected_count = arms[arm]["request_count"]
            check.expect(len(requests), expected_count, f"{name}/{arm}: request_count field")
            sums = {
                "aggregate_recomputed_tokens": sum(r["recomputed_tokens"] for r in requests),
                "aggregate_cached_tokens": sum(r["native_cached_prefix_tokens"] for r in requests),
                "aggregate_native_prompt_tokens": sum(r["native_prompt_tokens"] for r in requests),
                "aggregate_actual_prefill_tokens": sum(
                    r["actual_prefill_tokens"] for r in requests
                ),
                "aggregate_new_suffix_tokens": sum(r["new_suffix_tokens"] for r in requests),
            }
            for field_name, value in sums.items():
                check.expect(arms[arm][field_name], value, f"{name}/{arm}: {field_name}")

        base = {r["request_id"]: r for r in arms["A0"]["requests"]}
        for arm in COMPARED_ARMS:
            for row in arms[arm]["requests"]:
                base_row = base.get(row["request_id"])
                observations += 1
                comparisons += 1
                if base_row is None:
                    mismatches += 1
                    check.require(False, f"{name}/{arm}/{row['request_id']}: missing in A0")
                    continue
                if row["recomputed_tokens"] != base_row["recomputed_tokens"]:
                    mismatches += 1
                    check.require(
                        False, f"{name}/{arm}/{row['request_id']}: recomputed differs from A0"
                    )
                if row["eligible_prefix_tokens"] != base_row["eligible_prefix_tokens"]:
                    mismatches += 1
                    check.require(False, f"{name}/{arm}/{row['request_id']}: E differs from A0")

        # E must be arm-independent across all six arms, including N0.
        for arm in ARMS:
            for row in arms[arm]["requests"]:
                base_row = base.get(row["request_id"])
                if (
                    base_row is not None
                    and row["eligible_prefix_tokens"] != base_row["eligible_prefix_tokens"]
                ):
                    e_mismatches += 1
                    check.require(False, f"{name}/{arm}/{row['request_id']}: E differs across arms")

    check.expect(request_rows, EXPECTED["request_rows"], "request rows")
    check.expect(observations, EXPECTED["comparisons"], "comparisons")
    check.expect(comparisons, EXPECTED["comparisons"], "comparisons")
    check.expect(mismatches, EXPECTED["request_set_mismatches"], "per-request mismatches")
    check.expect(set_mismatches, 0, "request-set mismatches")
    check.expect(e_mismatches, 0, "E arm-independence mismatches")
    check.expect(arithmetic_failures, 0, "request arithmetic failures")
    check.detail.update(
        {
            "request_rows": request_rows,
            "observations": observations,
            "comparisons": comparisons,
            "mismatches": mismatches,
            "request_set_mismatches": set_mismatches,
            "e_mismatches": e_mismatches,
            "arithmetic_failures": arithmetic_failures,
        }
    )
    return check.detail


# ---------------------------------------------------------------------------
# B. A0 - N0 localisation and population arithmetic
# ---------------------------------------------------------------------------


def check_a0_n0(check: Check, cells: dict[str, dict], decisions: list[dict]) -> dict[str, Any]:
    decisions_by_cell = Counter(d["cell"] for d in decisions)
    diffs: list[dict] = []
    for name, cell in cells.items():
        order = [r["request_id"] for r in cell["arms"]["A0"]["requests"]]
        a0 = {r["request_id"]: r for r in cell["arms"]["A0"]["requests"]}
        n0 = {r["request_id"]: r for r in cell["arms"]["N0"]["requests"]}
        if not check.expect(set(a0), set(n0), f"{name}: A0/N0 request set"):
            continue
        changed = [
            rid for rid in order if a0[rid]["recomputed_tokens"] != n0[rid]["recomputed_tokens"]
        ]
        if not changed:
            continue
        delta = sum(a0[rid]["recomputed_tokens"] - n0[rid]["recomputed_tokens"] for rid in changed)
        is_last = changed == [order[-1]]
        check.require(is_last, f"{name}: difference is not exactly the last request: {changed}")
        diffs.append(
            {
                "cell": name,
                "group": cell["group_id"],
                "condition": cell["condition"],
                "delta": delta,
                "requests": changed,
                "decisions": decisions_by_cell[name],
            }
        )

    check.expect(len(diffs), EXPECTED["a0n0_diff_cells"], "A0-N0 difference cells")
    check.expect(
        sum(
            1
            for d in diffs
            if d["requests"] == [cells[d["cell"]]["arms"]["A0"]["requests"][-1]["request_id"]]
        ),
        EXPECTED["a0n0_last_request_cells"],
        "A0-N0 last-request cells",
    )
    total = sum(d["delta"] for d in diffs)
    check.expect(total, EXPECTED["a0n0_total_tokens"], "A0-N0 40-cell sum")

    h30_cells = [name for name in cells if name not in H3_EXCLUDED_CELLS]
    check.expect(len(h30_cells), EXPECTED["h30_cells"], "H3-0 cell count")
    h30_diffs = [d for d in diffs if d["cell"] in h30_cells]
    check.expect(len(h30_diffs), EXPECTED["h30_diff_cells"], "H3-0 difference cells")
    h30_cell_sum = sum(d["delta"] for d in h30_diffs)
    check.expect(h30_cell_sum, EXPECTED["h30_cell_sum_tokens"], "H3-0 cell sum")

    group_cells: dict[str, list[str]] = defaultdict(list)
    for name in h30_cells:
        group_cells[name.split("-")[0]].append(name)
    group_values = {
        group: sum(d["delta"] for d in h30_diffs if d["group"] == group) / len(group_cells[group])
        for group in group_cells
    }
    group_sum = sum(group_values.values())
    check.expect(
        round(group_sum, 6), float(EXPECTED["h30_group_sum_tokens"]), "H3-0 group-value sum"
    )
    zero_groups = sorted(group for group, value in group_values.items() if value == 0)
    check.expect(len(zero_groups), EXPECTED["h30_zero_groups"], "H3-0 zero groups")
    ranked = sorted(group_values.items(), key=lambda item: item[1])
    top5 = sum(value for _, value in ranked[:5])
    check.expect(round(pct(top5, group_sum), 1), EXPECTED["h30_top5_share_pct"], "H3-0 top-5 share")

    a0_group_values = {}
    for group, names in group_cells.items():
        a0_group_values[group] = sum(
            cells[name]["arms"]["A0"]["aggregate_recomputed_tokens"] for name in names
        ) / len(names)
    a0_group_mean = sum(a0_group_values.values()) / len(a0_group_values)
    check.expect(
        round(a0_group_mean, 1), EXPECTED["h30_a0_group_mean_tokens"], "H3-0 A0 group mean"
    )
    all_a0_cell_mean = sum(
        cell["arms"]["A0"]["aggregate_recomputed_tokens"] for cell in cells.values()
    ) / len(cells)
    check.expect(
        round(all_a0_cell_mean, 1),
        EXPECTED["all_a0_per_cell_mean_tokens"],
        "40-cell A0 per-cell mean",
    )
    ratio = pct(abs(-3123.2), a0_group_mean)
    check.expect(round(ratio, 1), EXPECTED["h30_over_a0_pct"], "H3-0 / A0 group mean percent")

    zero_decision_diffs = [d for d in diffs if d["decisions"] == 0]
    check.expect(
        len(zero_decision_diffs),
        EXPECTED["zero_decision_diff_cells"],
        "zero-decision A0-N0 difference cells",
    )
    if zero_decision_diffs:
        item = zero_decision_diffs[0]
        check.expect(item["cell"], "g18-c1", "zero-decision difference cell")
        check.expect(item["delta"], EXPECTED["g18_c1_delta"], "g18-c1 A0-N0 delta")
        check.warn(
            f"{item['cell']}: A0-N0 difference {item['delta']} with zero forced release; "
            "not attributable to release selection and excluded from H3-0"
        )
    check.expect(
        sum(1 for d in diffs if d["decisions"] > 0),
        19,
        "A0-N0 difference cells with at least one release",
    )

    by_4096 = sum(1 for d in diffs if d["delta"] == -4096)
    check.expect(by_4096, EXPECTED["cells_with_4096_delta"], "cells with -4096 delta")

    detail = {
        "cells_total": len(cells),
        "cells_with_difference": len(diffs),
        "difference_always_last_request": sum(
            1
            for d in diffs
            if d["requests"] == [cells[d["cell"]]["arms"]["A0"]["requests"][-1]["request_id"]]
        ),
        "sum_A0_minus_N0_tokens": total,
        "cells_with_difference_and_zero_decisions": [d["cell"] for d in zero_decision_diffs],
        "cells_with_difference_and_release": 19,
        "h30_cells": len(h30_cells),
        "h30_cells_with_difference": len(h30_diffs),
        "h30_cell_sum_tokens": h30_cell_sum,
        "h30_group_sum_tokens": round(group_sum, 6),
        "h30_zero_groups": zero_groups,
        "h30_top5_share_pct": round(pct(top5, group_sum), 1),
        "h30_a0_group_mean_tokens": round(a0_group_mean, 1),
        "all_a0_per_cell_mean_tokens": round(all_a0_cell_mean, 1),
        "h30_over_a0_pct": round(ratio, 1),
        "cells_with_minus_4096": by_4096,
        "per_cell": diffs,
    }
    check.detail.update(detail)
    return detail


# ---------------------------------------------------------------------------
# C. candidate completeness and independent ordering recomputation
# ---------------------------------------------------------------------------


def recompute_a3(audit: dict, need: int, timestamp: float) -> tuple[float, float, tuple]:
    q = reuse_proxy(audit["deadline"], timestamp)
    if not math.isclose(q, audit["reuse_proxy"], rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(f"{audit['key'][0]}: reuse_proxy {audit['reuse_proxy']} != recomputed {q}")
    score = q * audit["prefill_reload_seconds"] * audit["suffix_blocks"] / audit["chain_length"]
    if not math.isclose(score, audit["score"], rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(f"{audit['key'][0]}: A3 score {audit['score']} != recomputed {score}")
    order = (score, audit["deadline"], key_tuple(audit["key"]))
    return q, score, order


def recompute_a1(
    score_row: dict, need: int, timestamp: float, tau: float, lam: float
) -> tuple[float, float, tuple]:
    q = reuse_proxy(score_row["deadline"], timestamp, tau)
    if not math.isclose(q, score_row["reuse_proxy"], rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(
            f"{score_row['key'][0]}: A1 reuse_proxy {score_row['reuse_proxy']} != recomputed {q}"
        )
    forced = min(need, score_row["new_blocks"])
    residual = max(0, score_row["new_blocks"] - forced)
    expected = q * (forced + lam * residual)
    if not math.isclose(expected, score_row["expected_recompute"], rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError(
            f"{score_row['key'][0]}: A1 expected {score_row['expected_recompute']} != recomputed {expected}"
        )
    order = (expected, score_row["deadline"], key_tuple(score_row["key"]))
    return q, expected, order


def check_candidates_and_ordering(
    check: Check,
    cells: dict[str, dict],
    decisions: list[dict],
    csv_rows: list[dict[str, str]],
    evidence: Path,
) -> dict[str, Any]:
    # --- A3 audits: completeness, arithmetic, argmin -------------------------
    candidate_count = 0
    suffix_vs_need = Counter()
    new_blocks_ge_need = 0
    a3_recompute_ok = 0
    step2_count = 0
    q_monotone_ok = 0
    branch_ok = 0
    selected_ok = 0
    decision_distribution = Counter()
    suffix_identity_ok = 0

    for decision in decisions:
        need = decision["need"]
        if not isinstance(need, int):
            check.require(False, f"{decision['cell']}/{decision['decision_id']}: non-integer need")
            continue
        audits = decision["audits"]
        decision_distribution[len(audits)] += 1
        check.require(
            len({key_tuple(a["key"]) for a in audits}) == len(audits),
            f"{decision['cell']}/{decision['decision_id']}: duplicate audit key",
        )
        selected = [a for a in audits if a.get("selected") is True]
        check.expect(
            len(selected), 1, f"{decision['cell']}/{decision['decision_id']}: selected audit count"
        )
        if selected:
            check.expect(
                key_tuple(selected[0]["key"]),
                key_tuple(decision["selected_key"]),
                f"{decision['cell']}/{decision['decision_id']}: selected key",
            )
            if key_tuple(selected[0]["key"]) == key_tuple(decision["selected_key"]):
                selected_ok += 1

        need_from_audits = {a.get("need") for a in audits}
        check.require(
            need_from_audits == {need},
            f"{decision['cell']}/{decision['decision_id']}: audit need {need_from_audits} != {need}",
        )

        orders = []
        for audit in audits:
            candidate_count += 1
            for field_name in (
                "key",
                "deadline",
                "suffix_blocks",
                "chain_length",
                "d_min",
                "new_blocks",
                "prefill_reload_seconds",
                "reuse_proxy",
                "score",
            ):
                check.require(
                    field_name in audit,
                    f"{decision['cell']}/{decision['decision_id']}: missing {field_name}",
                )
            try:
                _, score, order = recompute_a3(audit, need, decision["timestamp"])
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                check.require(False, f"{decision['cell']}/{decision['decision_id']}: {exc}")
                continue
            orders.append(order)
            suffix_vs_need[
                "equal"
                if audit["suffix_blocks"] == need
                else ("greater" if audit["suffix_blocks"] > need else "less")
            ] += 1
            if audit["new_blocks"] >= need:
                new_blocks_ge_need += 1
            if audit["suffix_blocks"] == audit["chain_length"] - audit["d_min"] + 1:
                suffix_identity_ok += 1
            else:
                check.require(
                    False, f"{decision['cell']}/{decision['decision_id']}: suffix identity failed"
                )

        if len(orders) == len(audits):
            best = min(orders)
            if key_tuple(best[2]) == key_tuple(decision["selected_key"]):
                a3_recompute_ok += 1
            else:
                check.require(
                    False,
                    f"{decision['cell']}/{decision['decision_id']}: A3 selected is not argmin",
                )

        sufficient = step2_sufficient(need, audits)
        if need > 0 and sufficient:
            step2_count += 1
            if decision["branch"] == "single_step":
                branch_ok += 1
            else:
                check.require(
                    False,
                    f"{decision['cell']}/{decision['decision_id']}: branch {decision['branch']} != single_step",
                )

        ordered = sorted(audits, key=lambda a: a["deadline"])
        qs = [a["reuse_proxy"] for a in ordered]
        if all(qs[i] <= qs[i + 1] for i in range(len(qs) - 1)):
            q_monotone_ok += 1
        else:
            check.require(
                False,
                f"{decision['cell']}/{decision['decision_id']}: q is not increasing in deadline",
            )

    check.expect(candidate_count, EXPECTED["a3_candidates"], "A3 candidate count")
    check.expect(
        dict(sorted(decision_distribution.items())),
        {1: 120, 2: 7},
        "A3 candidate-count distribution",
    )
    check.expect(selected_ok, EXPECTED["a3_decisions"], "A3 selected audit consistency")
    check.expect(
        a3_recompute_ok, EXPECTED["a3_recompute_ok"], "A3 independent argmin recomputation"
    )
    check.expect(step2_count, EXPECTED["step2_sufficient"], "step2_sufficient count")
    check.expect(branch_ok, EXPECTED["step2_sufficient"], "single_step branch count")
    check.expect(q_monotone_ok, EXPECTED["a3_decisions"], "q monotone decisions")
    check.expect(suffix_identity_ok, EXPECTED["a3_candidates"], "suffix identity")
    check.expect(dict(suffix_vs_need), {"equal": 122, "greater": 12}, "suffix vs need")
    check.expect(new_blocks_ge_need, EXPECTED["new_blocks_ge_need"], "new_blocks >= need")

    # --- A3 CSV consistency -------------------------------------------------
    a3_rows = [row for row in csv_rows if row["arm"] == "A3"]
    check.expect(len(a3_rows), EXPECTED["a3_decisions"], "A3 CSV rows")
    by_key = {
        (decision["run"].rsplit("-", 1)[0], decision["decision_id"]): decision
        for decision in decisions
    }
    check.expect(len(by_key), len(decisions), "A3 decisions keyed by (run, decision_id)")
    csv_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in a3_rows:
        key = (row["run_id"].rsplit("-", 1)[0], row["decision_id"])
        check.require(key not in csv_by_key, f"duplicate A3 CSV key {key}")
        csv_by_key[key] = row
    check.expect(set(csv_by_key), set(by_key), "A3 CSV keys vs event keys")

    step_distribution = Counter()
    for key, decision in by_key.items():
        row = csv_by_key.get(key)
        if row is None:
            continue
        step_distribution[row["step"]] += 1
        audits = decision["audits"]
        selected = [a for a in audits if a.get("selected") is True]
        if not selected:
            continue
        chosen = selected[0]
        check.expect(
            parse_int(row["candidate_count"], "candidate_count"),
            len(audits),
            f"{key}: CSV candidate_count",
        )
        check.expect(
            parse_int(row["audit_candidate_count"], "audit_candidate_count"),
            len(audits),
            f"{key}: CSV audit_candidate_count",
        )
        check.expect(
            parse_int(row["sufficient_candidate_count"], "sufficient_candidate_count"),
            sum(1 for a in audits if a["new_blocks"] >= decision["need"]),
            f"{key}: CSV sufficient_candidate_count",
        )
        check.expect(
            parse_int(
                row["successfully_scored_candidate_count"], "successfully_scored_candidate_count"
            ),
            len(audits),
            f"{key}: CSV scored candidate count",
        )
        check.expect(parse_int(row["need"], "need"), decision["need"], f"{key}: CSV need")
        check.expect(
            row["selected_strategy_program"], chosen["key"][0], f"{key}: CSV selected program"
        )
        check.expect(selected_program(row), chosen["key"][0], f"{key}: CSV selected_programs")
        check.expect(
            parse_int(row["newly_eligible_blocks"], "newly_eligible_blocks"),
            chosen["new_blocks"],
            f"{key}: CSV newly_eligible_blocks",
        )
        check.expect(row["step"], "step2_sufficient", f"{key}: CSV step")
        check.expect(row["branch"], "single_step", f"{key}: CSV branch")
        if row["a3_vs_a1_same_program"] in {"True", "False"}:
            same = row["a3_vs_a1_same_program"] == "True"
            check.expect(
                same,
                chosen["key"][0] == row["a1_selected_program"],
                f"{key}: a3_vs_a1_same_program flag",
            )
    check.expect(dict(step_distribution), {"step2_sufficient": 127}, "CSV step distribution")

    # --- A1 traces: match to A3 by (cell, timestamp, program set) -----------
    a1_traces: dict[tuple[str, float, frozenset[str]], list[dict]] = defaultdict(list)
    a1_paths = sorted(evidence.glob("native-runs/*-a1/events.jsonl"))
    check.expect(len(a1_paths), EXPECTED["cells"], "A1 run count")
    for path in a1_paths:
        base_run = path.parent.name.rsplit("-", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("event_type") != "COST_AWARE_RELEASE_DECISION":
                continue
            trace = event.get("payload", {}).get("selection_trace") or []
            if not trace:
                continue
            step = trace[0]
            scores = step.get("scores") or []
            programs = frozenset(score["key"][0] for score in scores)
            a1_traces[(base_run, event["timestamp"], programs)].append(
                {"step": step, "payload": event["payload"], "timestamp": event["timestamp"]}
            )

    matched = 0
    a1_recompute_ok = 0
    a1_same_program = 0
    for decision in decisions:
        programs = frozenset(audit["key"][0] for audit in decision["audits"])
        key = (decision["run"].rsplit("-", 1)[0], decision["timestamp"], programs)
        matches = a1_traces.get(key, [])
        check.expect(
            len(matches), 1, f"{decision['cell']}/{decision['decision_id']}: A1 trace matches"
        )
        if len(matches) != 1:
            continue
        matched += 1
        trace = matches[0]
        step = trace["step"]
        scores = step.get("scores") or []
        check.expect(
            len(scores),
            len(decision["audits"]),
            f"{decision['cell']}/{decision['decision_id']}: A1 score count",
        )
        orders = []
        for score in scores:
            try:
                _, _, order = recompute_a1(
                    score,
                    decision["need"],
                    decision["timestamp"],
                    trace["payload"].get("tau_seconds", TAU_SECONDS),
                    trace["payload"].get("lambda", LAMBDA),
                )
            except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
                check.require(False, f"{decision['cell']}/{decision['decision_id']}: A1 {exc}")
                continue
            orders.append(order)
        if len(orders) == len(scores):
            best = min(orders)
            if best[2][0] == step["key"][0]:
                a1_recompute_ok += 1
            else:
                check.require(
                    False,
                    f"{decision['cell']}/{decision['decision_id']}: A1 selected is not argmin",
                )
        if step["key"][0] == decision["selected_key"][0]:
            a1_same_program += 1
        else:
            check.require(
                False, f"{decision['cell']}/{decision['decision_id']}: A1/A3 program differs"
            )

    check.expect(
        sum(len(v) for v in a1_traces.values()), EXPECTED["a3_decisions"], "A1 trace count"
    )
    check.expect(matched, EXPECTED["a3_decisions"], "A1/A3 trace matches")
    check.expect(
        a1_recompute_ok, EXPECTED["a1_recompute_ok"], "A1 independent argmin recomputation"
    )
    check.expect(a1_same_program, EXPECTED["same_program_all"], "A1/A3 same program")

    # --- A0 / E0: independent deadline ordering on the A3 candidate set -----
    a0_rows = {
        (row["run_id"].rsplit("-", 1)[0], row["decision_id"]): row
        for row in csv_rows
        if row["arm"] == "A0"
    }
    e0_rows = {
        (row["run_id"].rsplit("-", 1)[0], row["decision_id"]): row
        for row in csv_rows
        if row["arm"] == "E0"
    }
    a0_ok = 0
    e0_ok = 0
    a0_tie_warned = False
    for decision in decisions:
        key = (decision["run"].rsplit("-", 1)[0], decision["decision_id"])
        a0_row = a0_rows.get(key)
        e0_row = e0_rows.get(key)
        if a0_row is None or e0_row is None:
            check.require(False, f"{key}: missing A0/E0 CSV row")
            continue
        deadlines = [audit["deadline"] for audit in decision["audits"]]
        if len(set(deadlines)) != len(deadlines):
            if not a0_tie_warned:
                check.warn(
                    f"{key}: deadline tie present; A0/E0 exact tie-break cannot be checked from deadline alone"
                )
                a0_tie_warned = True
            continue
        a0_best = min(decision["audits"], key=lambda a: (a["deadline"], key_tuple(a["key"])))[
            "key"
        ][0]
        e0_best = min(decision["audits"], key=lambda a: (a["deadline"], key_tuple(a["key"])))[
            "key"
        ][0]
        a0_selected = selected_program(a0_row)
        e0_selected = selected_program(e0_row)
        check.expect(a0_selected, a0_best, f"{key}: A0 deadline argmin")
        check.expect(e0_selected, e0_best, f"{key}: E0 deadline argmin")
        if a0_selected == a0_best:
            a0_ok += 1
        if e0_selected == e0_best:
            e0_ok += 1

    check.expect(a0_ok, EXPECTED["a0_deadline_ok"], "A0 deadline recomputation")
    check.expect(e0_ok, EXPECTED["e0_deadline_ok"], "E0 deadline recomputation")

    # --- all four Entry arms same program -----------------------------------
    same_all = 0
    for decision in decisions:
        key = (decision["run"].rsplit("-", 1)[0], decision["decision_id"])
        a0_row = a0_rows.get(key)
        e0_row = e0_rows.get(key)
        a1_row = next(
            (
                row
                for row in a3_rows
                if (row["run_id"].rsplit("-", 1)[0], row["decision_id"]) == key
            ),
            None,
        )
        if not a0_row or not e0_row or not a1_row:
            continue
        a0_p = selected_program(a0_row)
        e0_p = selected_program(e0_row)
        a1_p = a1_row.get("a1_selected_program")
        a3_p = a1_row.get("selected_strategy_program")
        if a0_p == e0_p == a1_p == a3_p == decision["selected_key"][0]:
            same_all += 1
    check.expect(same_all, EXPECTED["same_program_all"], "A0/A1/A3/E0 same program")

    detail = {
        "decisions": len(decisions),
        "decision_cells": len({d["cell"] for d in decisions}),
        "candidates": candidate_count,
        "candidate_count_distribution": dict(sorted(decision_distribution.items())),
        "cell_decision_distribution": dict(
            sorted(Counter(Counter(d["cell"] for d in decisions).values()).items())
        ),
        "suffix_blocks_vs_need": dict(sorted(suffix_vs_need.items())),
        "new_blocks_ge_need": new_blocks_ge_need,
        "step2_sufficient": step2_count,
        "a3_recompute_ok": a3_recompute_ok,
        "a1_traces": sum(len(v) for v in a1_traces.values()),
        "a1_recompute_ok": a1_recompute_ok,
        "a1_a3_same_program": a1_same_program,
        "a0_deadline_ok": a0_ok,
        "e0_deadline_ok": e0_ok,
        "same_program_all": same_all,
        "q_monotone_decisions": q_monotone_ok,
        "suffix_identity_ok": suffix_identity_ok,
    }
    check.detail.update(detail)
    return detail


# ---------------------------------------------------------------------------
# D. eviction accounting
# ---------------------------------------------------------------------------


def check_eviction(check: Check, csv_rows: list[dict[str, str]]) -> dict[str, Any]:
    rows = [row for row in csv_rows if row["arm"] == "A3"]
    check.expect(len(rows), EXPECTED["a3_decisions"], "A3 eviction rows")

    matched_total = 0
    predicted_total = 0
    overlap_total = 0
    predicted_eq_need = 0
    matched_eq_need = 0
    physical_exceeds = 0
    predicted_flag_true = 0
    predicted_flag_consistent = 0
    required_eq_128 = 0
    required_distribution = Counter()

    for row in rows:
        need = parse_int(row["need"], "need")
        matched = parse_int(row["matched_physical_blocks"], "matched_physical_blocks")
        predicted = parse_int(row["predicted_victim_count"], "predicted_victim_count")
        overlap = parse_int(
            row["predicted_physical_overlap_count"], "predicted_physical_overlap_count"
        )
        required = parse_int(row["required_blocks"], "required_blocks")
        required_distribution[required] += 1
        matched_total += matched
        predicted_total += predicted
        overlap_total += overlap
        if predicted == need:
            predicted_eq_need += 1
        else:
            check.require(False, f"{row['run_id']}/{row['decision_id']}: predicted != need")
        if matched == need:
            matched_eq_need += 1
        if matched != need:
            physical_exceeds += 1
            check.expect(matched, 128, f"{row['run_id']}/{row['decision_id']}: physical excess")
            check.require(
                need < 128, f"{row['run_id']}/{row['decision_id']}: excess with need >= 128"
            )
        check.require(
            overlap == predicted,
            f"{row['run_id']}/{row['decision_id']}: overlap {overlap} != predicted {predicted}",
        )
        check.require(
            matched >= overlap,
            f"{row['run_id']}/{row['decision_id']}: matched {matched} < overlap {overlap}",
        )
        check.require(
            0 < required <= 128,
            f"{row['run_id']}/{row['decision_id']}: required_blocks {required} outside (0,128]",
        )
        check.require(
            required >= need,
            f"{row['run_id']}/{row['decision_id']}: required_blocks {required} < need {need}",
        )
        if required == 128:
            required_eq_128 += 1
        expected_flag = "True" if matched == need else "False"
        check.expect(
            row["predicted_equals_physical"],
            expected_flag,
            f"{row['run_id']}/{row['decision_id']}: predicted_equals_physical",
        )
        if row["predicted_equals_physical"] == expected_flag:
            predicted_flag_consistent += 1
        if row["predicted_equals_physical"] == "True":
            predicted_flag_true += 1
        check.expect(
            parse_int(row["unmatched_physical_blocks"], "unmatched_physical_blocks"),
            0,
            f"{row['run_id']}/{row['decision_id']}: unmatched blocks",
        )
        check.expect(
            parse_int(row["hashless_physical_blocks"], "hashless_physical_blocks"),
            0,
            f"{row['run_id']}/{row['decision_id']}: hashless blocks",
        )
        check.expect(
            row["downstream_recompute_attribution"],
            "NOT_ESTABLISHED",
            f"{row['run_id']}/{row['decision_id']}: downstream attribution",
        )

    check.expect(matched_total, EXPECTED["matched_physical_total"], "matched physical total")
    check.expect(predicted_total, EXPECTED["predicted_victim_total"], "predicted victim total")
    check.expect(
        overlap_total, EXPECTED["predicted_overlap_total"], "predicted/physical overlap total"
    )
    check.expect(predicted_eq_need, EXPECTED["predicted_eq_need"], "predicted == need")
    check.expect(matched_eq_need, EXPECTED["matched_eq_need"], "matched == need")
    check.expect(physical_exceeds, EXPECTED["physical_exceeds_need"], "physical exceeds need")
    check.expect(required_eq_128, EXPECTED["required_eq_128"], "required_blocks == 128")
    check.expect(
        predicted_flag_true, EXPECTED["predicted_flag_true"], "predicted_equals_physical True"
    )
    check.expect(
        predicted_flag_consistent,
        EXPECTED["predicted_flag_consistent"],
        "predicted_equals_physical consistency",
    )

    detail = {
        "decision_rows": len(rows),
        "matched_physical_blocks_total": matched_total,
        "predicted_victim_total": predicted_total,
        "predicted_physical_overlap_total": overlap_total,
        "predicted_victim_count_equals_need": f"{predicted_eq_need}/{len(rows)}",
        "matched_physical_blocks_equals_need": f"{matched_eq_need}/{len(rows)}",
        "rows_where_physical_exceeds_need": physical_exceeds,
        "predicted_equals_physical_true": f"{predicted_flag_true}/{len(rows)}",
        "predicted_equals_physical_consistent": f"{predicted_flag_consistent}/{len(rows)}",
        "required_blocks_eq_128": f"{required_eq_128}/{len(rows)}",
        "required_blocks_distribution": dict(sorted(required_distribution.items())),
    }
    check.detail.update(detail)
    return detail


# ---------------------------------------------------------------------------
# E. population, decision timing, and noise scope
# ---------------------------------------------------------------------------


def check_population_and_noise(
    check: Check,
    cells: dict[str, dict],
    decisions: list[dict],
    evidence: Path,
    main_report: dict,
    noise_report: dict,
    summary: dict,
) -> dict[str, Any]:
    # main-report population cross-checks
    check.expect(main_report["H3_0"]["cell_count"], EXPECTED["h30_cells"], "main-report H3-0 cells")
    check.expect(main_report["H3_0"]["group_count"], EXPECTED["groups"], "main-report H3-0 groups")
    check.expect(main_report["H3_R"]["cell_count"], EXPECTED["h3r_cells"], "main-report H3-R cells")
    check.expect(
        main_report["H3_R"]["group_count"], EXPECTED["h3r_groups"], "main-report H3-R groups"
    )
    check.expect(
        main_report["primary"]["N0"]["N_analyzed"],
        EXPECTED["primary_groups"],
        "main-report primary groups",
    )
    check.expect(
        main_report["H3_0"]["mean_A0_minus_N0"], -3123.2, "main-report H3-0 mean", tol=1e-9
    )
    check.expect(
        main_report["H3_R"]["mean_A0_minus_N0"],
        -6435.555555555556,
        "main-report H3-R mean",
        tol=1e-9,
    )
    check.expect(
        main_report["primary"]["N0"]["mean_delta"],
        1918.2222222222222,
        "main-report primary N0 mean",
        tol=1e-9,
    )

    primary_groups = {
        group for group in {name.split("-")[0] for name in cells} if group not in NON_PRIMARY_GROUPS
    }
    primary_cells = [name for name in cells if name.split("-")[0] in primary_groups]
    check.expect(len(primary_groups), EXPECTED["primary_groups"], "primary group count")
    check.expect(len(primary_cells), EXPECTED["primary_cells"], "primary cell count")
    h3r_groups = set(main_report["stratified_effects"]["N0"]["RESPONSIVE"]["group_ids"]) | {
        "g09",
        "g18",
    }
    h3r_cells = [
        name for name in cells if name.split("-")[0] in h3r_groups and name not in H3_EXCLUDED_CELLS
    ]
    check.expect(len(h3r_groups), EXPECTED["h3r_groups"], "H3-R derived group count")
    check.expect(len(h3r_cells), EXPECTED["h3r_cells"], "H3-R derived cell count")

    # decision timing: requests after the last forced release
    decisions_by_cell = Counter(d["cell"] for d in decisions)
    after_last_distribution = Counter()
    timing_failures = 0

    for name, cell in cells.items():
        events = None
        # Reuse the A3 event stream loaded on the decision (one representative).
        for decision in decisions:
            if decision["cell"] == name:
                events = decision["events"]
                break
        if events is None:
            continue
        forced = [e for e in events if e.get("event_type") == "FORCED_RELEASE_DECISION"]
        arrivals = [e for e in events if e.get("event_type") == "REQUEST_ARRIVED"]
        if not forced:
            check.expect(
                decisions_by_cell[name], 0, f"{name}: zero decisions without forced release"
            )
            continue
        last_forced = max(e["event_index"] for e in forced)
        after = [e for e in arrivals if e["event_index"] > last_forced]
        after_last_distribution[len(after)] += 1
        if len(after) not in (1, 2):
            timing_failures += 1
            check.require(False, f"{name}: {len(after)} requests after the last forced release")
        last_request = cell["arms"]["A0"]["requests"][-1]["request_id"]
        check.require(
            after and after[-1].get("request_id") == last_request,
            f"{name}: last request is not the last arrival after the last release",
        )
    check.expect(timing_failures, 0, "decision timing failures")

    # decisions per cell distribution
    per_cell = Counter(d["cell"] for d in decisions)
    dist = Counter(per_cell.values())
    check.expect(
        dict(sorted(dist.items())),
        EXPECTED["decision_cells_distribution"],
        "decisions per cell distribution",
    )

    # noise calibration coverage
    check.expect(noise_report["cell_count"], EXPECTED["noise_cells"], "noise cell_count")
    check.expect(noise_report["run_count"], EXPECTED["noise_runs"], "noise run_count")
    check.expect(noise_report["df"], EXPECTED["noise_df"], "noise df")
    check.expect(noise_report["sigma_run"], 0.0, "noise sigma_run")
    check.expect(noise_report["sigma_delta"], 0.0, "noise sigma_delta")
    check.expect(noise_report["tied_threshold"], 0.0, "noise tied threshold")

    noise_cells: dict[tuple[str, str], int] = Counter()
    noise_arms: set[str] = set()
    for path in sorted((evidence / "logs").glob("phase3-noise-*.log")):
        parts = path.stem.split("-")  # phase3-noise-g01-c1-a0-r1
        check.require(len(parts) == 6, f"{path.name}: unexpected noise log name")
        group, condition, arm, _ = parts[2], parts[3], parts[4], parts[5]
        noise_cells[(group, condition)] += 1
        noise_arms.add(arm)
    check.expect(len(noise_cells), EXPECTED["noise_cells"], "noise log cell count")
    check.expect(
        len({group for group, _ in noise_cells}), EXPECTED["noise_groups"], "noise log group count"
    )
    check.expect(sum(noise_cells.values()), EXPECTED["noise_runs"], "noise log run count")
    check.expect(noise_arms, {"a0"}, "noise calibration arms")
    check.require(
        all(count == 3 for count in noise_cells.values()), "noise cells do not all have R=3"
    )

    # summary cross-checks
    check.expect(summary["main_run_count"], 240, "summary main run count")
    check.expect(summary["a3"]["decision_count"], EXPECTED["a3_decisions"], "summary A3 decisions")
    check.expect(
        summary["a3"]["candidate_count_distribution"],
        {"1": 120, "2": 7},
        "summary A3 candidate distribution",
    )
    check.expect(summary["a3"]["step_counts"], {"step2_sufficient": 127}, "summary A3 steps")
    check.expect(summary["a3"]["a3_vs_a1_selection_differences"], 0, "summary A3/A1 differences")
    check.expect(
        summary["a3"]["genuine_multi_scored_opportunities"], 7, "summary multi opportunities"
    )
    check.expect(summary["g3_cm"]["discriminable_count"], 0, "summary discriminable decisions")
    check.expect(
        summary["a2"]["cost_known_count"], EXPECTED["a2_cost_known"], "summary A2 cost-known"
    )
    check.expect(
        summary["a2"]["selected_differs_from_native_lru_count"],
        EXPECTED["a2_differs_native"],
        "summary A2 native differences",
    )
    check.expect(
        summary["a2"]["search_truncated_count"], EXPECTED["a2_truncated"], "summary A2 truncation"
    )
    check.expect(summary["source_archive_sha256"], FROZEN_ARCHIVE_SHA256, "summary archive SHA-256")

    detail = {
        "cells": len(cells),
        "groups": len({name.split("-")[0] for name in cells}),
        "primary_groups": len(primary_groups),
        "primary_cells": len(primary_cells),
        "h30_groups": EXPECTED["groups"],
        "h30_cells": EXPECTED["h30_cells"],
        "h3r_groups": len(h3r_groups),
        "h3r_cells": len(h3r_cells),
        "noise_cells": len(noise_cells),
        "noise_groups": len({group for group, _ in noise_cells}),
        "noise_runs": sum(noise_cells.values()),
        "noise_arms": sorted(noise_arms),
        "noise_strata": noise_report.get("stratum_sigma_run"),
        "requests_after_last_release": dict(sorted(after_last_distribution.items())),
        "decision_cells_distribution": dict(sorted(dist.items())),
        "cells_with_zero_decisions": sorted(set(cells) - set(per_cell)),
        "archive_sha256": summary.get("source_archive_sha256"),
    }
    check.detail.update(detail)
    return detail


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def write_json(path: Path, payload: Any) -> None:
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

    probe = Probe()

    integrity = probe.check("A_input_integrity")
    for path, label in (
        (args.evidence, "evidence"),
        (args.evidence / "nec-cells", "nec-cells"),
        (args.evidence / "native-runs", "native-runs"),
        (args.evidence / "logs", "logs"),
        (args.audit, "audit"),
        (args.audit / "decision-audit.csv", "decision-audit.csv"),
        (args.audit / "summary.json", "summary.json"),
        (args.evidence / "main-report.json", "main-report.json"),
        (args.evidence / "noise-report.json", "noise-report.json"),
    ):
        integrity.require(path.exists(), f"missing required path: {path} ({label})")
    if not integrity.ok:
        return _finish(probe, args.out, "input paths missing")

    try:
        cells = load_cells(probe.check("B_cells"), args.evidence)
        decisions = load_decisions(probe.check("C_decisions"), args.evidence)
        csv_rows = load_csv_rows(probe.check("D_audit_csv"), args.audit)
        main_report = load_json(args.evidence / "main-report.json")
        noise_report = load_json(args.evidence / "noise-report.json")
        summary = load_json(args.audit / "summary.json")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        integrity.require(False, f"failed to load evidence: {exc}")
        return _finish(probe, args.out, "evidence load failed")

    try:
        check_request_integrity(probe.check("E_request_integrity"), cells)
        check_a0_n0(probe.check("F_a0_vs_n0"), cells, decisions)
        check_candidates_and_ordering(
            probe.check("G_candidate_and_ordering"), cells, decisions, csv_rows, args.evidence
        )
        check_eviction(probe.check("H_eviction_accounting"), csv_rows)
        check_population_and_noise(
            probe.check("I_population_and_noise"),
            cells,
            decisions,
            args.evidence,
            main_report,
            noise_report,
            summary,
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        probe.check("Z_runtime").require(False, f"unhandled probe error: {exc}")
        return _finish(probe, args.out, "probe error")

    return _finish(probe, args.out, None)


def _finish(probe: Probe, out: Path, fatal: str | None) -> int:
    payload = {
        "schema_version": "phase3.null_mechanism_probe.v2",
        "status": "PASS" if probe.ok and fatal is None else "FAIL",
        "checks": probe.as_dict(),
        "failures": probe.failures(),
        "warnings": probe.warnings(),
    }
    if fatal:
        payload["failures"].append(fatal)

    printed = False
    for item in probe.checks:
        if not item.detail:
            continue
        printed = True
        print(f"== {item.name} ==")
        for key, value in item.detail.items():
            if key in {"per_cell"}:
                continue
            print(f"  {key}: {value}")
        print()
    if not printed:
        print("== no checks completed ==")

    if payload["status"] != "PASS":
        print("STATUS FAIL")
        for failure in payload["failures"]:
            print(f"FAIL_CLOSED {failure}")

    try:
        out.mkdir(parents=True, exist_ok=True)
        write_json(out / "null-mechanism-probe.json", payload)
        print(f"== written to {out / 'null-mechanism-probe.json'}")
    except OSError as exc:
        print(
            f"FAIL_CLOSED cannot write {out / 'null-mechanism-probe.json'}: {exc}", file=sys.stderr
        )
        return 1

    if payload["status"] == "PASS":
        print("STATUS PASS")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
