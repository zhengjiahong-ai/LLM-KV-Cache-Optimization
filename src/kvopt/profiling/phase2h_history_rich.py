"""Fail-closed Gate H/D evaluation for Phase 2H history-rich Native runs."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Mapping
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


def _events(path: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError("event rows must be objects")
            rows.append(value)
    return tuple(rows)


def _of_type(
    rows: Iterable[Mapping[str, Any]], event_type: str
) -> list[Mapping[str, Any]]:
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


def _ttl_recomputation(
    history: Mapping[str, Any], decision: Mapping[str, Any]
) -> dict[str, Any]:
    source = history.get("payload", {})
    observed = decision.get("payload", {})
    ttl_input = TTLInput(
        program_id=ProgramIdentity(str(history["program_id"])),
        request_id=RequestIdentity(str(history["request_id"])),
        prefix_id=PrefixIdentity(str(history["prefix_id"])),
        decision_timestamp=float(decision["timestamp"]),
        next_tool_type=source.get("next_tool_type"),
        global_server_gap_samples_seconds=tuple(
            source["global_server_gap_samples_seconds"]
        ),
        tool_server_gap_samples_seconds=tuple(
            source["tool_server_gap_samples_seconds"]
        ),
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
        default_ttl_provenance=InputProvenance(
            InputSource.APPROXIMATED, "configured default TTL"
        ),
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
        "global_server_gap_sample_count": len(
            ttl_input.global_server_gap_samples_seconds
        ),
        "tool_server_gap_sample_count": len(
            ttl_input.tool_server_gap_samples_seconds
        ),
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
        if row["history_mode"] != "cold_start"
        and row["global_server_gap_sample_count"] > 100
    ]
    passed = bool(empirical) and missing == 0 and all(
        row["ttl_recomputed"] and row["deadline_recomputed"] for row in evidence
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
        and all(row["ttl_recomputed"] and row["deadline_recomputed"] for row in evidence),
    }


def _gate_d(rows: tuple[dict[str, Any], ...], arm: str) -> dict[str, Any]:
    forced = _of_type(rows, "FORCED_RELEASE_DECISION")
    multi = [
        row
        for row in forced
        if len(row.get("payload", {}).get("candidates", [])) >= 2
    ]
    traces = [
        row
        for row in _of_type(rows, "COST_AWARE_RELEASE_DECISION")
        if row.get("payload", {}).get("selection_trace")
    ]
    complete_traces = [
        trace
        for event in traces
        for trace in event["payload"]["selection_trace"]
        if int(trace.get("need", 0)) > 0
        and trace.get("key")
        and len(trace.get("scores", [])) >= 2
        and all(
            {"key", "new_blocks", "deadline", "reuse_proxy", "expected_recompute"}
            <= score.keys()
            for score in trace.get("scores", [])
        )
    ]
    opportunity = bool(multi)
    actual_a1 = arm == "A1"
    if actual_a1:
        passed = opportunity and bool(complete_traces)
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
        "complete_a1_scoring_iteration_count": len(complete_traces),
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
        "claim_boundary": (
            "Gate H and Gate D are independent; A0/A2 A1 scoring is shadow-only"
        ),
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
