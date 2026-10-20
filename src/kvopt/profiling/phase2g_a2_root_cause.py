"""Audit why the Phase 2G A2 Gate 2 mechanism was not established.

This is a read-only diagnostic over the sealed Native run artifacts.  It does
not alter the campaign, infer unobserved identities, or turn descriptive token
results into an A2 effectiveness conclusion.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path


def _events(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _payload(event: Mapping[str, object]) -> Mapping[str, object]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _distribution(values: Sequence[int]) -> dict[str, int | float | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
    }


def _counter(values: Sequence[object]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _forced_windows(events: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for position, event in enumerate(events):
        if event.get("event_type") != "FORCED_RELEASE_DECISION":
            continue
        payload = _payload(event)
        required = int(payload.get("required_blocks", 0))
        queue = payload.get("original_free_queue", [])
        decision_victims = [
            int(row["block_id"])
            for row in queue[:required]
            if isinstance(row, Mapping) and isinstance(row.get("block_id"), int)
        ]
        victims: list[int] = []
        for later in events[position + 1 :]:
            if later.get("event_type") == "FORCED_RELEASE_DECISION":
                break
            if later.get("event_type") == "BLOCK_EVICTED":
                block_id = _payload(later).get("block_id")
                if isinstance(block_id, int):
                    victims.append(block_id)
                if len(victims) == required:
                    break
        rows.append(
            {
                "event_index": int(event["event_index"]),
                "required_blocks": required,
                "decision_victims": decision_victims,
                "observed_hashed_evictions": victims,
                "decision_set_complete": len(decision_victims) == required,
                "tier_counts": _counter(
                    [
                        row.get("eligibility_tier")
                        for row in payload.get("original_free_queue", [])
                        if isinstance(row, Mapping)
                    ]
                ),
            }
        )
    return rows


def audit(
    *, run_root: Path, campaign_report: Path
) -> tuple[dict[str, object], list[dict[str, object]]]:
    report = json.loads(campaign_report.read_text(encoding="utf-8"))
    report_runs = {str(row["run_id"]): row for row in report["runs"]}
    decisions: list[dict[str, object]] = []
    a0_windows: dict[tuple[str, int], list[dict[str, object]]] = {}
    identity_states: Counter[str] = Counter()
    arm_requests: dict[str, Counter[str]] = {"A0": Counter(), "A2": Counter()}
    arm_metrics: dict[str, dict[str, list[int]]] = {
        policy: {name: [] for name in ("recomputed", "prefill", "suffix", "cached")}
        for policy in ("A0", "A2")
    }

    event_cache = {
        run_id: _events(run_root / run_id / "events.jsonl")
        for run_id, run in report_runs.items()
        if run.get("status") == "VALID"
    }
    for run_id, run in report_runs.items():
        if run.get("status") == "VALID" and run.get("policy") == "A0":
            key = (str(run["scenario_id"]), int(run["repeat"]))
            a0_windows[key] = _forced_windows(event_cache[run_id])

    for run_id, run in sorted(report_runs.items()):
        if run.get("status") != "VALID":
            continue
        policy = str(run["policy"])
        events = event_cache[run_id]
        key = (str(run["scenario_id"]), int(run["repeat"]))
        outcomes = run.get("request_outcomes", {})
        outcome_rows = outcomes.values() if isinstance(outcomes, Mapping) else outcomes
        for outcome in outcome_rows:
            if not isinstance(outcome, Mapping):
                continue
            cached = int(outcome.get("cached_prefix_tokens", 0))
            eligible = int(outcome.get("eligible_prefix_tokens", 0))
            native = int(outcome.get("prompt_tokens", 0))
            arm_metrics[policy]["recomputed"].append(eligible - cached)
            arm_metrics[policy]["prefill"].append(native - cached)
            arm_metrics[policy]["suffix"].append(native - eligible)
            arm_metrics[policy]["cached"].append(cached)
            if cached == 0:
                apc_outcome = "MISS"
            elif cached >= eligible:
                apc_outcome = "FULL_HIT"
            else:
                apc_outcome = "PARTIAL_HIT"
            arm_requests[policy][apc_outcome] += 1
        if policy != "A2":
            continue

        forced_events = [
            event
            for event in events
            if event.get("event_type") == "FORCED_RELEASE_DECISION"
        ]
        forced_by_next = {
            int(event["event_index"]) + 1: (ordinal, _payload(event))
            for ordinal, event in enumerate(forced_events)
        }
        report_decisions = {
            int(row["event_index"]): row for row in run.get("decision_rows", [])
        }
        for event in events:
            if event.get("event_type") != "COST_AWARE_BLOCK_DECISION":
                continue
            payload = _payload(event)
            index = int(event["event_index"])
            legal = [int(value) for value in payload.get("legal_block_ids", [])]
            selected = [int(value) for value in payload.get("selected_victims", [])]
            reference = [int(value) for value in payload.get("native_lru_victims", [])]
            legal_hash_rows = payload.get("legal_content_hashes", [])
            hashed = sum(
                1
                for row in legal_hash_rows
                if isinstance(row, Mapping) and isinstance(row.get("content_hash"), str)
            )
            decision_row = report_decisions.get(index, {})
            identity_states.update(decision_row.get("legal_identity_states", {}).values())
            forced_context = forced_by_next.get(index)
            ordinal = forced_context[0] if forced_context is not None else None
            forced_payload = forced_context[1] if forced_context is not None else {}
            tier_counts = _counter(
                [
                    row.get("eligibility_tier")
                    for row in forced_payload.get("original_free_queue", [])
                    if isinstance(row, Mapping)
                ]
            )
            a0_actual = None
            if ordinal is not None:
                windows = a0_windows.get(key, [])
                if ordinal < len(windows):
                    a0_actual = windows[ordinal]["decision_victims"]
            decisions.append(
                {
                    "run_id": run_id,
                    "scenario_id": run["scenario_id"],
                    "family": run["family"],
                    "repeat": run["repeat"],
                    "event_index": index,
                    "forced_release_associated": ordinal is not None,
                    "selector": payload.get("selector"),
                    "fallbacks": list(payload.get("fallbacks", [])),
                    "contract_problems": list(payload.get("contract_problems", [])),
                    "adapter_problems": list(payload.get("adapter_problems", [])),
                    "legal_candidate_count": len(legal),
                    "required_blocks": int(payload.get("required_blocks", 0)),
                    "hashed_legal_count": hashed,
                    "hashless_legal_count": len(legal) - hashed,
                    "identified_hashed_block_count": int(
                        payload.get("identified_hashed_block_count", 0)
                    ),
                    "chain_count": int(payload.get("chain_count", 0)),
                    "shared_block_count": int(payload.get("shared_block_count", 0)),
                    "tier_counts": tier_counts,
                    "native_lru_matches_legal_prefix": reference
                    == legal[: len(reference)],
                    "selected_equals_native_lru": set(selected) == set(reference),
                    "a0_actual_victim_set": a0_actual,
                    "a2_native_lru_reference_set": reference,
                    "a2_selected_set": selected,
                    "a0_actual_equals_a2_reference": (
                        set(a0_actual) == set(reference)
                        if a0_actual is not None
                        else None
                    ),
                }
            )

    fallback_reasons = Counter(
        str(reason) for row in decisions for reason in row["fallbacks"]
    )
    contract_problems = Counter(
        str(problem) for row in decisions for problem in row["contract_problems"]
    )
    adapter_problems = Counter(
        str(problem) for row in decisions for problem in row["adapter_problems"]
    )
    pair_none = sum(row.get("selection_diverged") is None for row in report["pairs"])
    pair_false = sum(row.get("selection_diverged") is False for row in report["pairs"])
    unmapped = sum(int(row.get("unmapped_physical_eviction_count", 0)) for row in report["runs"])
    strict_physical = sum(int(row.get("physical_eviction_count", 0)) for row in report["runs"])
    associated_tiers: Counter[str] = Counter()
    for row in decisions:
        if row["forced_release_associated"]:
            associated_tiers.update(row["tier_counts"])
    all_a0_windows = [window for windows in a0_windows.values() for window in windows]
    result: dict[str, object] = {
        "schema_version": "phase2g.a2_gate2_root_cause_audit.v1",
        "scope": "READ_ONLY_EXISTING_144_RUN_EVIDENCE",
        "formal_effectiveness_conclusion": "INCONCLUSIVE",
        "a2_decision_count": len(decisions),
        "selector_counts": _counter([row["selector"] for row in decisions]),
        "fallback_reason_counts": dict(sorted(fallback_reasons.items())),
        "contract_problem_counts": dict(sorted(contract_problems.items())),
        "adapter_problem_counts": dict(sorted(adapter_problems.items())),
        "identity_state_counts": dict(sorted(identity_states.items())),
        "forced_release_associated_decision_count": sum(
            bool(row["forced_release_associated"]) for row in decisions
        ),
        "native_allocation_decision_count": sum(
            not bool(row["forced_release_associated"]) for row in decisions
        ),
        "candidate_distributions": {
            field: _distribution([int(row[field]) for row in decisions])
            for field in (
                "legal_candidate_count",
                "required_blocks",
                "hashed_legal_count",
                "hashless_legal_count",
                "identified_hashed_block_count",
                "chain_count",
                "shared_block_count",
            )
        },
        "selected_equals_native_lru_count": sum(
            bool(row["selected_equals_native_lru"]) for row in decisions
        ),
        "native_lru_matches_legal_prefix_count": sum(
            bool(row["native_lru_matches_legal_prefix"]) for row in decisions
        ),
        "forced_release_legal_tier_counts": dict(sorted(associated_tiers.items())),
        "a0_forced_window_count": len(all_a0_windows),
        "a0_decision_set_complete_count": sum(
            bool(row["decision_set_complete"]) for row in all_a0_windows
        ),
        "a0_observed_hashed_eviction_count": sum(
            len(row["observed_hashed_evictions"]) for row in all_a0_windows
        ),
        "forced_a0_actual_equals_a2_reference_counts": _counter(
            [
                row["a0_actual_equals_a2_reference"]
                for row in decisions
                if row["forced_release_associated"]
            ]
        ),
        "request_metrics_by_policy": {
            policy: {
                "apc_outcome_counts": dict(sorted(arm_requests[policy].items())),
                **{
                    name: {
                        **_distribution(values),
                        "sum": sum(values),
                    }
                    for name, values in arm_metrics[policy].items()
                },
            }
            for policy in ("A0", "A2")
        },
        "not_realized_decomposition": {
            "explicit_content_unverified_fallback_decisions": fallback_reasons.get(
                "content_unverified", 0
            ),
            "greedy_but_selected_equals_lru_decisions": sum(
                row["selector"] == "incremental_greedy"
                and row["selected_equals_native_lru"]
                for row in decisions
            ),
            "decisions_with_shared_blocks": sum(
                int(row["shared_block_count"]) > 0 for row in decisions
            ),
            "pair_selection_unobservable_count": pair_none,
            "pair_selection_proven_equal_count": pair_false,
            "strict_physical_eviction_count": strict_physical,
            "unmapped_physical_eviction_count": unmapped,
        },
        "interpretation": [
            "Zero token delta is descriptive and is not evidence that A2 equals LRU.",
            "All-None selection observations remain unobservable, not proven false.",
            "Physical-event coexistence is not per-block recomputation causality.",
        ],
    }
    return result, decisions


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value
                    for key, value in row.items()
                }
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--campaign-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decision-table", type=Path, required=True)
    args = parser.parse_args(argv)
    result, decisions = audit(
        run_root=args.run_root, campaign_report=args.campaign_report
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    _write_csv(args.decision_table, decisions)
    print(f"wrote A2 root-cause audit: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
