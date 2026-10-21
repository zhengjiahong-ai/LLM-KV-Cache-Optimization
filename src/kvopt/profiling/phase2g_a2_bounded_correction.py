"""Bounded offline correction for the Phase 2G A2 value evaluation.

The correction never compares physical block ids across Native processes.  It
uses the content geometry that was observed before each decision to express a
victim as its set of ``(program_id, chain_position)`` memberships.  Forced
release windows are paired only when their ordinal, required capacity, and
released program set agree.  Ordinary allocation decisions are reported
separately because the A0 arm did not persist an equivalent decision event.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

SemanticBlock = tuple[tuple[str, int], ...]
HASHLESS: SemanticBlock = (("__HASHLESS_NO_CONTENT__", -1),)


def _load(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _payload(event: Mapping[str, object]) -> Mapping[str, object]:
    value = event.get("payload")
    return value if isinstance(value, Mapping) else {}


def _semantic_state(
    events: Sequence[Mapping[str, object]],
) -> dict[int, dict[int, SemanticBlock]]:
    """Return current content memberships immediately before every event."""
    memberships: dict[int, set[tuple[str, int]]] = defaultdict(set)
    states: dict[int, dict[int, SemanticBlock]] = {}
    for event in events:
        index = int(event["event_index"])
        states[index] = {
            block_id: tuple(sorted(values)) for block_id, values in memberships.items() if values
        }
        if event.get("event_type") == "VLLM_PREFIX_SNAPSHOT":
            program = event.get("program_id")
            block_ids = _payload(event).get("block_ids", ())
            if isinstance(program, str) and isinstance(block_ids, (list, tuple)):
                for position, value in enumerate(block_ids):
                    memberships[int(value)].add((program, position))
        elif event.get("event_type") == "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED":
            block_id = _payload(event).get("block_id")
            if isinstance(block_id, int):
                memberships.pop(block_id, None)
    return states


def _semantic_set(
    block_ids: Sequence[object], state: Mapping[int, SemanticBlock]
) -> list[SemanticBlock] | None:
    result: list[SemanticBlock] = []
    for value in block_ids:
        identity = state.get(int(value))
        if not identity:
            return None
        result.append(identity)
    return sorted(result)


def _release_programs(payload: Mapping[str, object]) -> tuple[str, ...]:
    releases = payload.get("selected_releases", ())
    if not isinstance(releases, (list, tuple)):
        return ()
    return tuple(
        sorted(
            str(row["program_id"])
            for row in releases
            if isinstance(row, Mapping) and isinstance(row.get("program_id"), str)
        )
    )


def _candidate_semantics(payload: Mapping[str, object]) -> dict[int, SemanticBlock]:
    """Recover decision-time membership from the persisted retention candidates."""
    memberships: dict[int, set[tuple[str, int]]] = defaultdict(set)
    candidates = payload.get("candidates", ())
    if not isinstance(candidates, (list, tuple)):
        return {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        program = candidate.get("program_id")
        block_ids = candidate.get("block_ids", ())
        if not isinstance(program, str) or not isinstance(block_ids, (list, tuple)):
            continue
        for position, value in enumerate(block_ids):
            memberships[int(value)].add((program, position))
    return {block_id: tuple(sorted(values)) for block_id, values in memberships.items()}


def _decision_semantics(payload: Mapping[str, object]) -> dict[int, SemanticBlock]:
    """Recover verified memberships and explicit hashless state from A2 evidence."""
    result: dict[int, SemanticBlock] = {}
    memberships = payload.get("block_memberships", ())
    if isinstance(memberships, (list, tuple)):
        for row in memberships:
            if not isinstance(row, Mapping):
                continue
            block_id = int(row["block_id"])
            values: set[tuple[str, int]] = set()
            for membership in row.get("memberships", ()):
                if not isinstance(membership, Mapping):
                    continue
                chain_id = membership.get("chain_id")
                depth = membership.get("depth")
                if isinstance(chain_id, str) and isinstance(depth, int):
                    values.add((chain_id.split(":", 1)[0], depth - 1))
            if values:
                result[block_id] = tuple(sorted(values))
    hashes = payload.get("legal_content_hashes", ())
    if isinstance(hashes, (list, tuple)):
        for row in hashes:
            if (
                isinstance(row, Mapping)
                and row.get("content_hash") is None
                and isinstance(row.get("block_id"), int)
            ):
                result[int(row["block_id"])] = HASHLESS
    return result


def _forced_rows(events: Sequence[Mapping[str, object]], *, policy: str) -> list[dict[str, object]]:
    states = _semantic_state(events)
    rows: list[dict[str, object]] = []
    for ordinal, event in enumerate(
        row for row in events if row.get("event_type") == "FORCED_RELEASE_DECISION"
    ):
        index = int(event["event_index"])
        payload = _payload(event)
        required = int(payload.get("required_blocks", 0))
        queue = payload.get("original_free_queue", ())
        queue_rows = (
            [row for row in queue if isinstance(row, Mapping)]
            if isinstance(queue, (list, tuple))
            else []
        )
        semantic_state = _candidate_semantics(payload) or states[index]
        for row in queue_rows:
            if row.get("has_block_hash") is False:
                semantic_state[int(row["block_id"])] = HASHLESS
        actual_ids = [int(row["block_id"]) for row in queue_rows[:required]]
        rows.append(
            {
                "ordinal": ordinal,
                "event_index": index,
                "policy": policy,
                "required_blocks": required,
                "release_programs": _release_programs(payload),
                "actual_victim_semantics": _semantic_set(actual_ids, semantic_state),
                "tier_counts": dict(
                    Counter(str(row.get("eligibility_tier")) for row in queue_rows)
                ),
            }
        )
    return rows


def _a2_decisions(events: Sequence[Mapping[str, object]]) -> tuple[list[dict[str, object]], int]:
    states = _semantic_state(events)
    forced = [row for row in events if row.get("event_type") == "FORCED_RELEASE_DECISION"]
    forced_indices = [int(row["event_index"]) for row in forced]
    rows: list[dict[str, object]] = []
    ordinary = 0
    for event in events:
        if event.get("event_type") != "COST_AWARE_BLOCK_DECISION":
            continue
        index = int(event["event_index"])
        preceding = [i for i, value in enumerate(forced_indices) if value < index]
        ordinal = (
            preceding[-1] if preceding and index == forced_indices[preceding[-1]] + 1 else None
        )
        if ordinal is None:
            ordinary += 1
            continue
        payload = _payload(event)
        forced_payload = _payload(forced[ordinal])
        state = (
            _decision_semantics(payload) or _candidate_semantics(forced_payload) or states[index]
        )
        rows.append(
            {
                "ordinal": ordinal,
                "event_index": index,
                "release_programs": _release_programs(_payload(forced[ordinal])),
                "required_blocks": int(payload.get("required_blocks", 0)),
                "selector": payload.get("selector"),
                "fallbacks": list(payload.get("fallbacks", ())),
                "legal_semantics": _semantic_set(payload.get("legal_block_ids", ()), state),
                "selected_semantics": _semantic_set(payload.get("selected_victims", ()), state),
                "internal_lru_semantics": _semantic_set(
                    payload.get("native_lru_victims", ()), state
                ),
            }
        )
    return rows, ordinary


def _request_rows(
    report_runs: Mapping[str, Mapping[str, object]], scenarios: set[str]
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, int, str], Mapping[str, object]] = {}
    for run in report_runs.values():
        scenario = str(run.get("scenario_id"))
        if scenario in scenarios and run.get("status") == "VALID":
            outcomes = run.get("request_outcomes", {})
            if isinstance(outcomes, Mapping):
                for request_id, outcome in outcomes.items():
                    if isinstance(outcome, Mapping):
                        grouped[
                            (scenario, int(run["repeat"]), str(run["policy"]), str(request_id))
                        ] = outcome
    rows: list[dict[str, object]] = []

    def outcome(cached: int, eligible: int) -> str:
        if cached == 0:
            return "MISS"
        if cached >= eligible:
            return "FULL_HIT"
        return "PARTIAL_HIT"

    keys = {(s, r, q) for s, r, _p, q in grouped}
    for scenario, repeat, request_id in sorted(keys):
        a0 = grouped.get((scenario, repeat, "A0", request_id))
        a2 = grouped.get((scenario, repeat, "A2", request_id))
        if a0 is None or a2 is None:
            continue

        def metric(row: Mapping[str, object], name: str) -> int:
            return int(row.get(name, 0))

        a0_e, a2_e = metric(a0, "eligible_prefix_tokens"), metric(a2, "eligible_prefix_tokens")
        a0_c, a2_c = metric(a0, "cached_prefix_tokens"), metric(a2, "cached_prefix_tokens")
        delta = (a2_e - a2_c) - (a0_e - a0_c)
        if delta:
            rows.append(
                {
                    "scenario_id": scenario,
                    "repeat": repeat,
                    "request_id": request_id,
                    "a0_eligible_prefix_tokens": a0_e,
                    "a0_cached_prefix_tokens": a0_c,
                    "a0_native_cache_outcome": outcome(a0_c, a0_e),
                    "a2_eligible_prefix_tokens": a2_e,
                    "a2_cached_prefix_tokens": a2_c,
                    "a2_native_cache_outcome": outcome(a2_c, a2_e),
                    "delta_recomputed_tokens_a2_minus_a0": delta,
                }
            )
    return rows


def evaluate(
    *, run_root: Path, campaign_report: Path
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    report = json.loads(campaign_report.read_text(encoding="utf-8"))
    runs = {str(row["run_id"]): row for row in report["runs"]}
    a0_by_key: dict[tuple[str, int], list[dict[str, object]]] = {}
    a2_by_key: dict[tuple[str, int], tuple[list[dict[str, object]], int]] = {}
    for run_id, run in runs.items():
        if run.get("status") != "VALID":
            continue
        events = _load(run_root / run_id / "events.jsonl")
        key = (str(run["scenario_id"]), int(run["repeat"]))
        if run["policy"] == "A0":
            a0_by_key[key] = _forced_rows(events, policy="A0")
        else:
            a2_by_key[key] = _a2_decisions(events)

    comparisons: list[dict[str, object]] = []
    ordinary_count = 0
    for key in sorted(set(a0_by_key) | set(a2_by_key)):
        a0_rows = a0_by_key.get(key, [])
        a2_rows, ordinary = a2_by_key.get(key, ([], 0))
        ordinary_count += ordinary
        for ordinal in range(max(len(a0_rows), len(a2_rows))):
            a0 = a0_rows[ordinal] if ordinal < len(a0_rows) else None
            a2 = a2_rows[ordinal] if ordinal < len(a2_rows) else None
            window_match = bool(
                a0
                and a2
                and a0["required_blocks"] == a2["required_blocks"]
                and a0["release_programs"] == a2["release_programs"]
            )
            identity_complete = bool(
                a0
                and a2
                and a0["actual_victim_semantics"] is not None
                and a2["selected_semantics"] is not None
                and a2["internal_lru_semantics"] is not None
                and a2["legal_semantics"] is not None
            )
            comparisons.append(
                {
                    "scenario_id": key[0],
                    "repeat": key[1],
                    "window_ordinal": ordinal,
                    "window_pairable": window_match,
                    "identity_complete": identity_complete,
                    "selector": a2.get("selector") if a2 else None,
                    "fallbacks": a2.get("fallbacks") if a2 else None,
                    "a2_vs_internal_lru_diverged": (
                        a2["selected_semantics"] != a2["internal_lru_semantics"]
                        if identity_complete
                        else None
                    ),
                    "a2_vs_actual_a0_diverged": (
                        a2["selected_semantics"] != a0["actual_victim_semantics"]
                        if window_match and identity_complete
                        else None
                    ),
                    "a0_vs_internal_lru_reference_diverged": (
                        a0["actual_victim_semantics"] != a2["internal_lru_semantics"]
                        if window_match and identity_complete
                        else None
                    ),
                }
            )

    f4_requests = _request_rows(runs, {"f4-draw-04", "f4-draw-05", "f4-draw-06"})
    f4_repeat_deltas: dict[str, int] = defaultdict(int)
    for row in f4_requests:
        key = f"{row['scenario_id']}/repeat-{row['repeat']}"
        f4_repeat_deltas[key] += int(row["delta_recomputed_tokens_a2_minus_a0"])
    actual_values = [row["a2_vs_actual_a0_diverged"] for row in comparisons]
    result = {
        "schema_version": "phase2g.a2_bounded_offline_correction.v1",
        "scope": "EXISTING_144_RUN_EVIDENCE_ONLY",
        "forced_window_comparison_count": len(comparisons),
        "ordinary_allocation_decision_count": ordinary_count,
        "ordinary_allocation_classification": "NO_EQUIVALENT_A0_DECISION_EVENT_NOT_COMPARABLE",
        "pairable_complete_forced_window_count": sum(
            row["window_pairable"] and row["identity_complete"] for row in comparisons
        ),
        "a2_vs_internal_lru_divergence_count": sum(
            row["a2_vs_internal_lru_diverged"] is True for row in comparisons
        ),
        "a2_vs_actual_a0_divergence_count": sum(value is True for value in actual_values),
        "a0_vs_internal_lru_reference_divergence_count": sum(
            row["a0_vs_internal_lru_reference_diverged"] is True for row in comparisons
        ),
        "unobservable_or_unpairable_forced_window_count": sum(
            value is None for value in actual_values
        ),
        "f4_nonzero_request_delta_row_count": len(f4_requests),
        "f4_repeat_delta_recomputed_tokens_a2_minus_a0": dict(sorted(f4_repeat_deltas.items())),
        "answer": "INCONCLUSIVE_BASELINE_COMPARISON_AND_NATIVE_ATTRIBUTION_GAPS_REMAIN",
        "limitations": [
            "Physical block ids and process-local Native hashes are never compared across arms.",
            "Ordinary allocation has no equivalent persisted A0 decision event.",
            "A request-level token delta is not automatically attributed to one victim decision.",
        ],
    }
    return result, comparisons, f4_requests


def _csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--campaign-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--decision-table", type=Path, required=True)
    parser.add_argument("--f4-request-table", type=Path, required=True)
    args = parser.parse_args(argv)
    result, decisions, requests = evaluate(
        run_root=args.run_root, campaign_report=args.campaign_report
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _csv(args.decision_table, decisions)
    _csv(args.f4_request_table, requests)
    print(f"wrote bounded offline correction: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
