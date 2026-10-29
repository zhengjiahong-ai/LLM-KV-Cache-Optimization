"""Fail-closed Gate H/D evaluation for Phase 2H history-rich Native runs."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from kvopt.continuum.snapshots import TTLInput
from kvopt.continuum.ttl import estimate_ttl
from kvopt.continuum.types import (
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
)
from kvopt.costaware.a1_entry import A1EntryCostAwareStrategy
from kvopt.costaware.replay import DecisionSnapshot, QueueBlock, ReplayState
from kvopt.profiling.datasets import DecisionCandidateRow


def _events(path: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError("event rows must be objects")
            rows.append(value)
    return tuple(rows)


def _of_type(rows: Iterable[Mapping[str, Any]], event_type: str) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get("event_type") == event_type]


def _provenance(payload: Mapping[str, Any]) -> InputProvenance:
    source = InputSource(str(payload["server_gap_history_provenance_source"]))
    reason = payload.get("server_gap_history_provenance_reason")
    return InputProvenance(source, None if reason is None else str(reason))


def _named_provenance(
    payload: Mapping[str, Any], prefix: str, fallback_reason: str
) -> InputProvenance:
    source = InputSource(str(payload[f"{prefix}_provenance_source"]))
    reason = payload.get(f"{prefix}_provenance_reason")
    if reason is None and source in {InputSource.APPROXIMATED, InputSource.UNAVAILABLE}:
        reason = fallback_reason
    return InputProvenance(source, None if reason is None else str(reason))


def _ttl_recomputation(history: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    source = history.get("payload", {})
    observed = decision.get("payload", {})
    ttl_input = TTLInput(
        program_id=ProgramIdentity(str(history["program_id"])),
        request_id=RequestIdentity(str(history["request_id"])),
        prefix_id=PrefixIdentity(str(history["prefix_id"])),
        decision_timestamp=float(decision["timestamp"]),
        next_tool_type=source.get("next_tool_type"),
        global_server_gap_samples_seconds=tuple(source["global_server_gap_samples_seconds"]),
        tool_server_gap_samples_seconds=tuple(source["tool_server_gap_samples_seconds"]),
        queue_delay_t_seconds=float(source["queue_delay_t_seconds"]),
        eta=float(source["eta"]),
        prefill_reload_seconds=float(source["prefill_reload_seconds"]),
        default_ttl_seconds=float(source["default_ttl_seconds"]),
        server_gap_history_provenance=_provenance(source),
        queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
        eta_provenance=_named_provenance(source, "eta", "persisted ETA input"),
        prefill_reload_provenance=_named_provenance(
            source, "prefill_reload", "persisted profile estimate"
        ),
        default_ttl_provenance=InputProvenance(InputSource.APPROXIMATED, "configured default TTL"),
    )
    recomputed = estimate_ttl(
        ttl_input,
        duration_history_threshold=int(source["duration_history_threshold"]),
    )
    ttl_matches = math.isclose(
        recomputed.ttl_seconds,
        float(observed["ttl_seconds"]),
        rel_tol=0.0,
        abs_tol=1e-9,
    )
    deadline_matches = math.isclose(
        recomputed.deadline_timestamp,
        float(observed["deadline_timestamp"]),
        rel_tol=0.0,
        abs_tol=1e-9,
    )
    return {
        "history_mode": str(observed["history_mode"]),
        "history_mode_recomputed": recomputed.history_mode.value,
        "history_mode_matches": (str(observed["history_mode"]) == recomputed.history_mode.value),
        "global_server_gap_sample_count": len(ttl_input.global_server_gap_samples_seconds),
        "tool_server_gap_sample_count": len(ttl_input.tool_server_gap_samples_seconds),
        "ttl_recomputed": ttl_matches,
        "deadline_recomputed": deadline_matches,
    }


def _gate_h(rows: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    histories = _of_type(rows, "TTL_HISTORY_INPUT_OBSERVED")
    decisions = _of_type(rows, "TTL_DECISION_OBSERVED")
    by_key = {
        (row.get("program_id"), row.get("request_id"), row.get("prefix_id")): row
        for row in decisions
    }
    evidence: list[dict[str, Any]] = []
    missing = 0
    for history in histories:
        key = (
            history.get("program_id"),
            history.get("request_id"),
            history.get("prefix_id"),
        )
        decision = by_key.get(key)
        if decision is None:
            missing += 1
            continue
        try:
            evidence.append(_ttl_recomputation(history, decision))
        except (KeyError, TypeError, ValueError):
            missing += 1
    empirical = [
        row
        for row in evidence
        if row["history_mode"] != "cold_start" and row["global_server_gap_sample_count"] > 100
    ]
    passed = (
        bool(empirical)
        and missing == 0
        and all(
            row["ttl_recomputed"] and row["deadline_recomputed"] and row["history_mode_matches"]
            for row in evidence
        )
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "history_decision_count": len(evidence),
        "missing_or_invalid_decision_count": missing,
        "empirical_ttl_decision_count": len(empirical),
        "maximum_global_server_gap_sample_count": max(
            (row["global_server_gap_sample_count"] for row in evidence), default=0
        ),
        "all_ttl_and_deadlines_recomputed": bool(evidence)
        and all(
            row["ttl_recomputed"] and row["deadline_recomputed"] and row["history_mode_matches"]
            for row in evidence
        ),
    }


def _key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row["program_id"]), str(row["prefix_id"])


def _recompute_a1(
    decision: Mapping[str, Any], lambda_: float, tau: float
) -> tuple[list[dict[str, Any]], list[tuple[tuple[str, str], tuple[int, ...]]]]:
    payload = decision["payload"]
    candidates = payload["candidates"]
    queue = tuple(
        QueueBlock(
            block_id=int(row["block_id"]),
            has_block_hash=bool(row["has_block_hash"]),
            native_lru_rank=int(row["native_lru_rank"]),
        )
        for row in payload["original_free_queue"]
    )
    candidate_keys = tuple(_key(row) for row in candidates)
    owners: dict[int, set[tuple[str, str]]] = {}
    for candidate in candidates:
        key = _key(candidate)
        for block_id in candidate["block_ids"]:
            owners.setdefault(int(block_id), set()).add(key)
    selected = tuple(_key(row) for row in payload["selected_releases"])
    snapshot = DecisionSnapshot(
        run_id="phase2h-independent-gate-d",
        decision_event_index=int(decision.get("event_index", 0)),
        timestamp=float(decision["timestamp"]),
        required_blocks=int(payload["required_blocks"]),
        queue=queue,
        candidate_keys=candidate_keys,
        owners_by_block={key: frozenset(value) for key, value in owners.items()},
        observed_selected=selected,
        observed_initial_reclaimable={
            _key(row): tuple(int(value) for value in row["initially_reclaimable_block_ids"])
            for row in candidates
        },
        ranking_by_block={row.block_id: row.native_lru_rank for row in queue},
    )
    selected_order = {key: index for index, key in enumerate(selected)}
    rows = tuple(
        DecisionCandidateRow(
            run_id=snapshot.run_id,
            decision_event_index=snapshot.decision_event_index,
            source_event_index=snapshot.decision_event_index,
            candidate_position=position,
            program_id=key[0],
            prefix_id=key[1],
            selected=key in selected_order,
            release_order=selected_order.get(key),
            retention_deadline_timestamp=float(candidate["retention_deadline_timestamp"]),
            waiting_followup=bool(candidate["waiting_followup"]),
            block_ids=tuple(int(value) for value in candidate["block_ids"]),
            block_count=len(candidate["block_ids"]),
            initially_reclaimable_block_ids=tuple(
                int(value) for value in candidate["initially_reclaimable_block_ids"]
            ),
            initially_reclaimable_block_count=len(candidate["initially_reclaimable_block_ids"]),
            next_tool_type=candidate.get("next_tool_type"),
            elapsed_since_ttl_decision_seconds=float(
                candidate["elapsed_since_ttl_decision_seconds"]
            ),
            prefill_reload_seconds=float(candidate["prefill_reload_seconds"]),
            eta=float(candidate["eta"]),
            queue_delay_t_seconds=float(candidate["queue_delay_t_seconds"]),
            decision_native_lru_position=None,
        )
        for position, (candidate, key) in enumerate(zip(candidates, candidate_keys, strict=True))
    )
    strategy = A1EntryCostAwareStrategy(lambda_=lambda_, tau_seconds=tau)
    state = ReplayState(snapshot)
    traces: list[dict[str, Any]] = []
    releases: list[tuple[tuple[str, str], tuple[int, ...]]] = []
    while len(state.eligible_block_ids()) < snapshot.target:
        remaining = [row for row in rows if (row.program_id, row.prefix_id) not in state.released]
        selection = strategy.select(remaining, state)
        traces.append(asdict(selection))
        releases.append((selection.key, tuple(state.newly_eligible_after(selection.key))))
        state.release(selection.key)
    return traces, releases


def _trace_matches(observed: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    if observed.keys() != expected.keys():
        return False
    for key, value in expected.items():
        actual = observed[key]
        if isinstance(value, float):
            if not math.isclose(float(actual), value, rel_tol=0.0, abs_tol=1e-12):
                return False
        elif isinstance(value, (tuple, list)):
            if len(actual) != len(value):
                return False
            if any(
                not _trace_matches(a, b) if isinstance(b, Mapping) else a != b
                for a, b in zip(actual, value, strict=True)
            ):
                return False
        elif actual != value:
            return False
    return True


def _gate_d(rows: tuple[dict[str, Any], ...], arm: str) -> dict[str, Any]:
    forced = _of_type(rows, "FORCED_RELEASE_DECISION")
    multi = [row for row in forced if len(row.get("payload", {}).get("candidates", [])) >= 2]
    traces = [
        row
        for row in _of_type(rows, "COST_AWARE_RELEASE_DECISION")
        if row.get("payload", {}).get("selection_trace")
    ]
    opportunity = bool(multi)
    actual_a1 = arm == "A1"
    recomputed = 0
    invalid = 0
    if actual_a1:
        unused = list(traces)
        for decision in multi:
            selected = tuple(_key(row) for row in decision["payload"]["selected_releases"])
            matches = [
                event
                for event in unused
                if tuple(tuple(trace["key"]) for trace in event["payload"]["selection_trace"])
                == selected
            ]
            if len(matches) != 1:
                invalid += 1
                continue
            event = matches[0]
            unused.remove(event)
            try:
                expected, expected_releases = _recompute_a1(
                    decision,
                    float(event["payload"]["lambda"]),
                    float(event["payload"]["tau_seconds"]),
                )
                observed = event["payload"]["selection_trace"]
                observed_releases = [
                    (
                        _key(row),
                        tuple(int(value) for value in row["newly_eligible_block_ids"]),
                    )
                    for row in decision["payload"]["selected_releases"]
                ]
                if (
                    observed_releases != expected_releases
                    or len(observed) != len(expected)
                    or not all(
                        _trace_matches(actual, wanted)
                        for actual, wanted in zip(observed, expected, strict=True)
                    )
                ):
                    invalid += 1
                    continue
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            recomputed += 1
        passed = opportunity and recomputed == len(multi) and invalid == 0
        status = "PASS" if passed else "FAIL"
        scope = "ACTUAL_A1_EXECUTION"
    else:
        status = "NOT_APPLICABLE_SHADOW_ONLY"
        scope = "SHADOW_DIAGNOSTIC_NOT_EXECUTED"
    return {
        "status": status,
        "candidate_opportunity_status": "PASS" if opportunity else "FAIL",
        "scoring_evidence_scope": scope,
        "forced_release_decision_count": len(forced),
        "multi_candidate_decision_count": len(multi),
        "independently_recomputed_decision_count": recomputed,
        "invalid_or_unmatched_decision_count": invalid,
    }


def evaluate_run(run_dir: Path, *, arm: str) -> dict[str, Any]:
    """Evaluate one completed run without aggregating away partial gates."""
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    rows = _events(run_dir / "events.jsonl")
    return {
        "schema_version": "phase2h.history_rich_gate_report.v1",
        "run_id": run.get("run_id", run_dir.name),
        "arm": arm,
        "execution_status": run.get("status"),
        "gate_h": _gate_h(rows),
        "gate_d": _gate_d(rows, arm),
        "claim_boundary": ("Gate H and Gate D are independent; A0/A2 A1 scoring is shadow-only"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--arm", choices=("A0", "A1", "A2"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = evaluate_run(arguments.run_dir, arm=arguments.arm)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Gate H={report['gate_h']['status']} "
        f"Gate D={report['gate_d']['status']}: {arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
