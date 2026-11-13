"""Read-only Phase 3 Algorithm Exposure audit.

The analyzer consumes the immutable Option F evidence archive and emits compact,
deterministic CSV/JSON derivatives.  It never edits or extracts into the source
archive.  Native block selection, physical eviction, and downstream recompute
remain separate evidence tiers throughout the output.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import tarfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAIN_RUN_RE = re.compile(r"phase3-main-(g\d{2})-(c[12])-r(\d+)-(n0|a0|a1|a2|a3|e0)$")
ARMS = ("n0", "a0", "a1", "a2", "a3", "e0")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_cell(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _program(key: object) -> str:
    if isinstance(key, list) and key and isinstance(key[0], str):
        return key[0]
    return ""


def _rank(values: list[float]) -> list[float]:
    """Average ranks with deterministic tie handling."""

    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = (cursor + end - 1) / 2.0
        for index in order[cursor:end]:
            ranks[index] = rank
        cursor = end
    return ranks


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    x = _rank(left)
    y = _rank(right)
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y, strict=True))
    x_norm = math.sqrt(sum((a - x_mean) ** 2 for a in x))
    y_norm = math.sqrt(sum((b - y_mean) ** 2 for b in y))
    if x_norm == 0.0 or y_norm == 0.0:
        return None
    return numerator / (x_norm * y_norm)


@dataclass
class RunEvidence:
    run_id: str
    group_id: str
    condition: str
    repeat: int
    arm: str
    pressure_attempts: int = 0
    pressure_events: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


def _read_main_runs(archive: Path) -> list[RunEvidence]:
    runs: list[RunEvidence] = []
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            if not member.isfile() or not member.name.endswith("/events.jsonl"):
                continue
            run_id = member.name.split("/")[-2]
            match = MAIN_RUN_RE.fullmatch(run_id)
            if match is None:
                continue
            handle = bundle.extractfile(member)
            if handle is None:
                raise ValueError(f"cannot read {member.name}")
            evidence = RunEvidence(
                run_id=run_id,
                group_id=match.group(1),
                condition=match.group(2).upper(),
                repeat=int(match.group(3)),
                arm=match.group(4),
            )
            for raw in handle:
                event = json.loads(raw)
                evidence.events.append(event)
                if event.get("event_type") == "CONTROLLED_REPLAY_PRESSURE_COMPLETED":
                    evidence.pressure_events += 1
                    evidence.pressure_attempts += int(
                        event.get("payload", {}).get("attempt_count", 0)
                    )
            runs.append(evidence)
    runs.sort(key=lambda row: row.run_id)
    expected = 20 * 2 * 6
    if len(runs) != expected or len({row.run_id for row in runs}) != expected:
        raise ValueError(f"expected {expected} unique Main runs, observed {len(runs)}")
    return runs


def _strategy_type(arm: str) -> str | None:
    return {
        "a1": "COST_AWARE_RELEASE_DECISION",
        "a2": "COST_AWARE_BLOCK_DECISION",
        "a3": "A3_SUFFIX_RELEASE_DECISION",
        "e0": "E0_DEADLINE_RELEASE_DECISION",
    }.get(arm)


def _analyze_run(run: RunEvidence) -> tuple[list[dict[str, object]], dict[str, object]]:
    bindings: dict[int, dict[str, Any]] = {}
    plans: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, dict[str, Any]] = {}
    strategy_events: list[dict[str, Any]] = []
    strategy_by_decision: dict[str, dict[str, Any]] = {}
    forced_events: list[dict[str, Any]] = []
    a2_all = Counter()
    strategy_type = _strategy_type(run.arm)

    for event in run.events:
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        if event_type == "FORCED_RELEASE_DECISION":
            forced_events.append(event)
        elif event_type == "FORCED_RELEASE_DECISION_BINDING":
            bindings[int(payload["forced_release_event_index"])] = payload
        elif event_type == "NATIVE_ENTRY_RELEASE_SELECTION_PLAN":
            plans[str(payload.get("decision_id", ""))] = payload
        elif event_type == "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME":
            outcomes[str(payload.get("decision_id", ""))] = payload
        if strategy_type is not None and event_type == strategy_type:
            strategy_events.append(event)
            strategy_decision_id = str(payload.get("decision_id", ""))
            if strategy_decision_id:
                strategy_by_decision[strategy_decision_id] = event
            if run.arm == "a2":
                a2_all[f"selector:{payload.get('selector', 'MISSING')}"] += 1
                a2_all[f"cost_known:{bool(payload.get('cost_known'))}"] += 1
                a2_all[f"search_truncated:{bool(payload.get('search_truncated'))}"] += 1
                if payload.get("fallbacks"):
                    a2_all["fallback_event"] += 1

    rows: list[dict[str, object]] = []
    for ordinal, event in enumerate(forced_events, start=1):
        event_index = int(event.get("event_index", -1))
        payload = event.get("payload", {})
        binding = bindings.get(event_index, {})
        decision_id = str(binding.get("decision_id", f"UNBOUND:{event_index}"))
        plan = plans.get(decision_id, {})
        outcome = outcomes.get(decision_id, {})

        relevant = strategy_by_decision.get(decision_id)
        if relevant is None and strategy_events:
            previous_forced = (
                int(forced_events[ordinal - 2].get("event_index", -1)) if ordinal > 1 else -1
            )
            next_forced = (
                int(forced_events[ordinal].get("event_index", 2**63))
                if ordinal < len(forced_events)
                else 2**63
            )
            window = [
                candidate
                for candidate in strategy_events
                if previous_forced < int(candidate.get("event_index", -1)) < next_forced
                and (candidate.get("payload", {}).get("selection_trace", []) or run.arm == "a2")
            ]
            if window:
                relevant = min(
                    window,
                    key=lambda candidate: abs(int(candidate.get("event_index", -1)) - event_index),
                )
        strategy = (relevant or {}).get("payload", {})
        trace_items = strategy.get("selection_trace", [])
        trace = trace_items[0] if trace_items else {}

        required_blocks = int(payload.get("required_blocks", 0))
        need = trace.get("need")
        candidates = payload.get("candidates", [])
        sufficient_count: int | str = ""
        if isinstance(need, int):
            sufficient_count = sum(
                len(item.get("initially_reclaimable_block_ids", [])) >= need for item in candidates
            )

        scored: list[dict[str, Any]] = []
        audits = list(trace.get("audits", []))
        if run.arm == "a1":
            scored = list(trace.get("scores", []))
        elif run.arm in {"a3", "e0"}:
            scored = [
                audit
                for audit in audits
                if audit.get("score") is not None and not audit.get("fallback_reason")
            ]

        branch = str(trace.get("branch", ""))
        step = str(trace.get("step", ""))
        fallback_reason = str(trace.get("fallback_reason", ""))
        fell_back = bool(trace.get("fell_back", False))
        if run.arm == "a2":
            branch = str(strategy.get("selector", ""))
            fallback_reason = ";".join(map(str, strategy.get("fallbacks", [])))
            fell_back = bool(strategy.get("fallbacks")) or not bool(
                strategy.get("cost_known", False)
            )

        selected_programs = [
            str(item.get("program_id", "")) for item in payload.get("selected_releases", [])
        ]
        selected_key = trace.get("key", [])
        deadlines = [float(item["deadline"]) for item in scored if "deadline" in item]
        scores = [float(item.get("score", item.get("expected_recompute"))) for item in scored]
        score_gap: float | str = ""
        relative_gap: float | str = ""
        rank_correlation: float | str = ""
        cost_deadline_same_top: bool | str = ""
        if len(scores) >= 2:
            ordered = sorted(scores)
            score_gap = ordered[1] - ordered[0]
            relative_gap = score_gap / max(abs(ordered[0]), 1e-15)
            correlation = _spearman(scores, deadlines)
            rank_correlation = "" if correlation is None else correlation
            cost_top = min(range(len(scores)), key=lambda i: (scores[i], deadlines[i], i))
            deadline_top = min(range(len(scores)), key=lambda i: (deadlines[i], i))
            cost_deadline_same_top = cost_top == deadline_top

        native_lru = strategy.get("native_lru_victims", [])
        selected_victims = strategy.get("selected_victims", [])
        a2_native_equal: bool | str = ""
        if run.arm == "a2" and native_lru:
            a2_native_equal = selected_victims == native_lru
        predicted_victims = plan.get("a3_predicted_victim_block_ids", [])
        matched_physical = outcome.get("matched_block_ids", [])
        predicted_overlap: int | str = ""
        predicted_exact: bool | str = ""
        if predicted_victims:
            predicted_overlap = len(set(predicted_victims) & set(matched_physical))
            predicted_exact = set(predicted_victims) == set(matched_physical)

        rows.append(
            {
                "run_id": run.run_id,
                "group_id": run.group_id,
                "condition": run.condition,
                "arm": run.arm.upper(),
                "decision_ordinal": ordinal,
                "decision_id": decision_id,
                "forced_event_index": event_index,
                "strategy_event_index": (relevant or {}).get("event_index", ""),
                "pressure_attempts_run": run.pressure_attempts,
                "required_blocks": required_blocks,
                "need": "" if need is None else need,
                "candidate_count": len(candidates),
                "sufficient_candidate_count": sufficient_count,
                "successfully_scored_candidate_count": len(scored),
                "audit_candidate_count": len(audits),
                "content_verified_candidate_count": sum(
                    bool(audit.get("content_verified")) for audit in audits
                ),
                "prefill_evidence_candidate_count": sum(
                    isinstance(audit.get("prefill_reload_seconds"), (int, float))
                    and not isinstance(audit.get("prefill_reload_seconds"), bool)
                    and float(audit["prefill_reload_seconds"]) > 0.0
                    for audit in audits
                ),
                "complete_victim_geometry_candidate_count": sum(
                    bool(audit.get("victim_block_ids"))
                    and len(audit.get("victim_block_ids", []))
                    == len(audit.get("victim_depths", []))
                    for audit in audits
                ),
                "branch": branch,
                "step": step,
                "fell_back": fell_back,
                "fallback_reason": fallback_reason,
                "selected_programs": _json_cell(selected_programs),
                "selected_strategy_program": _program(selected_key),
                "selected_release_count": len(payload.get("selected_releases", [])),
                "newly_eligible_blocks": sum(
                    len(item.get("newly_eligible_block_ids", []))
                    for item in payload.get("selected_releases", [])
                ),
                "score_gap_top2": score_gap,
                "relative_score_gap_top2": relative_gap,
                "score_deadline_rank_correlation": rank_correlation,
                "cost_deadline_same_top": cost_deadline_same_top,
                "a1_selected_program": _program(trace.get("a1_key", [])),
                "a3_vs_a1_same_program": (
                    _program(selected_key) == _program(trace.get("a1_key", []))
                    if run.arm == "a3" and selected_key
                    else ""
                ),
                "a2_selector": strategy.get("selector", ""),
                "a2_cost_known": strategy.get("cost_known", ""),
                "a2_search_truncated": strategy.get("search_truncated", ""),
                "a2_identified_hashed_blocks": strategy.get("identified_hashed_block_count", ""),
                "a2_selected_equals_native_lru": a2_native_equal,
                "selection_plan_present": bool(plan),
                "selection_plan_block_count": len(plan.get("selected_native_block_ids", [])),
                "predicted_victim_count": len(predicted_victims),
                "predicted_physical_overlap_count": predicted_overlap,
                "predicted_equals_physical": predicted_exact,
                "physical_outcome_present": bool(outcome),
                "physical_outcome_status": outcome.get("status", ""),
                "matched_physical_blocks": len(outcome.get("matched_block_ids", [])),
                "unmatched_physical_blocks": len(outcome.get("unmatched_block_ids", [])),
                "hashless_physical_blocks": len(outcome.get("hashless_block_ids", [])),
                "downstream_recompute_attribution": "NOT_ESTABLISHED",
            }
        )

    diagnostics = {
        "run_id": run.run_id,
        "group_id": run.group_id,
        "condition": run.condition,
        "arm": run.arm.upper(),
        "pressure_events": run.pressure_events,
        "pressure_attempts": run.pressure_attempts,
        "forced_release_count": len(forced_events),
        "strategy_event_count": len(strategy_events),
        "a2_all_event_diagnostics": dict(sorted(a2_all.items())),
    }
    return rows, diagnostics


def _summary_rows(
    decision_rows: list[dict[str, object]],
    run_diagnostics: list[dict[str, object]],
    classification: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    by_arm: dict[str, list[dict[str, object]]] = defaultdict(list)
    by_cell: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    runs_by_arm: dict[str, list[dict[str, object]]] = defaultdict(list)
    runs_by_cell: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in decision_rows:
        arm = str(row["arm"])
        by_arm[arm].append(row)
        by_cell[(str(row["group_id"]), str(row["condition"]), arm)].append(row)
    for row in run_diagnostics:
        match = MAIN_RUN_RE.fullmatch(str(row["run_id"]))
        assert match is not None
        runs_by_arm[match.group(4).upper()].append(row)
        runs_by_cell[(str(row["group_id"]), str(row["condition"]), str(row["arm"]))].append(row)

    def aggregate(
        arm: str,
        rows: list[dict[str, object]],
        runs: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "arm": arm,
            "run_count": len(runs),
            "pressure_event_count": sum(int(x["pressure_events"]) for x in runs),
            "pressure_request_count": sum(int(x["pressure_attempts"]) for x in runs),
            "forced_release_count": len(rows),
            "candidate_total": sum(int(x["candidate_count"]) for x in rows),
            "multi_candidate_decisions": sum(int(x["candidate_count"]) > 1 for x in rows),
            "multi_scored_decisions": sum(
                int(x["successfully_scored_candidate_count"]) > 1 for x in rows
            ),
            "fallback_decisions": sum(bool(x["fell_back"]) for x in rows),
            "newly_eligible_blocks": sum(int(x["newly_eligible_blocks"]) for x in rows),
            "physical_outcomes": sum(bool(x["physical_outcome_present"]) for x in rows),
            "matched_physical_blocks": sum(int(x["matched_physical_blocks"]) for x in rows),
            "unmatched_physical_blocks": sum(int(x["unmatched_physical_blocks"]) for x in rows),
        }

    global_rows = [
        aggregate(arm.upper(), by_arm[arm.upper()], runs_by_arm[arm.upper()]) for arm in ARMS
    ]
    cell_rows: list[dict[str, object]] = []
    for group in [f"g{index:02d}" for index in range(1, 21)]:
        for condition in ("C1", "C2"):
            for arm in (name.upper() for name in ARMS):
                key = (group, condition, arm)
                result = aggregate(arm, by_cell[key], runs_by_cell[key])
                group_classification = classification.get(group, {})
                condition_data = group_classification.get(condition, {})
                result.update(
                    {
                        "group_id": group,
                        "condition": condition,
                        "pressure_response_stratum": group_classification.get(
                            "pressure_response_stratum", ""
                        ),
                        "rho0": (
                            condition_data.get("rho0", "")
                            if isinstance(condition_data, dict)
                            else ""
                        ),
                    }
                )
                cell_rows.append(result)
    return global_rows, cell_rows


def _pairwise_rows(decisions: list[dict[str, object]]) -> list[dict[str, object]]:
    def selected_program(row: dict[str, object]) -> str:
        strategy_program = str(row["selected_strategy_program"])
        if strategy_program:
            return strategy_program
        releases = json.loads(str(row["selected_programs"]))
        return str(releases[0]) if len(releases) == 1 else _json_cell(releases)

    indexed = {
        (
            str(row["group_id"]),
            str(row["condition"]),
            str(row["arm"]),
            int(row["decision_ordinal"]),
        ): row
        for row in decisions
    }
    rows: list[dict[str, object]] = []
    for group in [f"g{i:02d}" for i in range(1, 21)]:
        for condition in ("C1", "C2"):
            for left, right in (("A0", "A1"), ("A0", "A2"), ("A3", "E0")):
                count = min(
                    sum(key[:3] == (group, condition, left) for key in indexed),
                    sum(key[:3] == (group, condition, right) for key in indexed),
                )
                diverged = False
                for ordinal in range(1, count + 1):
                    first = indexed[(group, condition, left, ordinal)]
                    second = indexed[(group, condition, right, ordinal)]
                    left_program = selected_program(first)
                    right_program = selected_program(second)
                    same = left_program == right_program
                    rows.append(
                        {
                            "group_id": group,
                            "condition": condition,
                            "decision_ordinal": ordinal,
                            "left_arm": left,
                            "right_arm": right,
                            "left_run_id": first["run_id"],
                            "right_run_id": second["run_id"],
                            "left_decision_id": first["decision_id"],
                            "right_decision_id": second["decision_id"],
                            "same_selected_program": same,
                            "trajectory_already_diverged": diverged,
                            "comparison_status": (
                                "DIAGNOSTIC_POST_DIVERGENCE"
                                if diverged
                                else "PAIRED_PRE_DIVERGENCE"
                            ),
                        }
                    )
                    diverged = diverged or not same
    return rows


DECISION_FIELDS = [
    "run_id",
    "group_id",
    "condition",
    "arm",
    "decision_ordinal",
    "decision_id",
    "forced_event_index",
    "strategy_event_index",
    "pressure_attempts_run",
    "required_blocks",
    "need",
    "candidate_count",
    "sufficient_candidate_count",
    "successfully_scored_candidate_count",
    "audit_candidate_count",
    "content_verified_candidate_count",
    "prefill_evidence_candidate_count",
    "complete_victim_geometry_candidate_count",
    "branch",
    "step",
    "fell_back",
    "fallback_reason",
    "selected_programs",
    "selected_strategy_program",
    "selected_release_count",
    "newly_eligible_blocks",
    "score_gap_top2",
    "relative_score_gap_top2",
    "score_deadline_rank_correlation",
    "cost_deadline_same_top",
    "a1_selected_program",
    "a3_vs_a1_same_program",
    "a2_selector",
    "a2_cost_known",
    "a2_search_truncated",
    "a2_identified_hashed_blocks",
    "a2_selected_equals_native_lru",
    "selection_plan_present",
    "selection_plan_block_count",
    "predicted_victim_count",
    "predicted_physical_overlap_count",
    "predicted_equals_physical",
    "physical_outcome_present",
    "physical_outcome_status",
    "matched_physical_blocks",
    "unmatched_physical_blocks",
    "hashless_physical_blocks",
    "downstream_recompute_attribution",
]

SUMMARY_FIELDS = [
    "arm",
    "run_count",
    "pressure_event_count",
    "pressure_request_count",
    "forced_release_count",
    "candidate_total",
    "multi_candidate_decisions",
    "multi_scored_decisions",
    "fallback_decisions",
    "newly_eligible_blocks",
    "physical_outcomes",
    "matched_physical_blocks",
    "unmatched_physical_blocks",
]

CELL_PREFIX_FIELDS = ["group_id", "condition", "pressure_response_stratum", "rho0"]

PAIRWISE_FIELDS = [
    "group_id",
    "condition",
    "decision_ordinal",
    "left_arm",
    "right_arm",
    "left_run_id",
    "right_run_id",
    "left_decision_id",
    "right_decision_id",
    "same_selected_program",
    "trajectory_already_diverged",
    "comparison_status",
]


def analyze_phase3_algorithm_exposure(
    archive: Path, output: Path, classification_path: Path | None = None
) -> dict[str, object]:
    """Analyze one immutable evidence archive and write deterministic derivatives."""

    archive = archive.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    decisions: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    classification: dict[str, dict[str, object]] = {}
    classification_sha256 = ""
    if classification_path is not None:
        classification_path = classification_path.resolve()
        classification_document = json.loads(classification_path.read_text(encoding="utf-8"))
        classification = {str(row["group_id"]): row for row in classification_document["groups"]}
        classification_sha256 = _sha256(classification_path)
    for run in _read_main_runs(archive):
        run_rows, run_diagnostics = _analyze_run(run)
        decisions.extend(run_rows)
        diagnostics.append(run_diagnostics)
    global_rows, cell_rows = _summary_rows(decisions, diagnostics, classification)
    pairwise = _pairwise_rows(decisions)
    fallback_counts = Counter(
        (str(row["arm"]), str(row["fallback_reason"]) or "NONE") for row in decisions
    )
    fallback_rows = [
        {"arm": arm, "fallback_reason": reason, "count": count}
        for (arm, reason), count in sorted(fallback_counts.items())
    ]

    _write_csv(output / "global-summary.csv", global_rows, SUMMARY_FIELDS)
    _write_csv(
        output / "group-condition-summary.csv",
        cell_rows,
        [*CELL_PREFIX_FIELDS, *SUMMARY_FIELDS],
    )
    _write_csv(output / "decision-audit.csv", decisions, DECISION_FIELDS)
    _write_csv(
        output / "strategy-pairwise-comparison.csv",
        pairwise,
        PAIRWISE_FIELDS,
    )
    _write_csv(
        output / "fallback-reason-distribution.csv",
        fallback_rows,
        ["arm", "fallback_reason", "count"],
    )

    a3 = [row for row in decisions if row["arm"] == "A3"]
    a2 = [row for row in decisions if row["arm"] == "A2"]
    summary = {
        "schema_version": "phase3.algorithm_exposure_audit.v1",
        "source_archive": archive.name,
        "source_archive_sha256": _sha256(archive),
        "classification_sha256": classification_sha256,
        "main_run_count": 240,
        "decision_row_count": len(decisions),
        "a3": {
            "decision_count": len(a3),
            "step_counts": dict(sorted(Counter(str(row["step"]) for row in a3).items())),
            "candidate_count_distribution": dict(
                sorted(Counter(str(row["candidate_count"]) for row in a3).items())
            ),
            "scored_candidate_count_distribution": dict(
                sorted(
                    Counter(str(row["successfully_scored_candidate_count"]) for row in a3).items()
                )
            ),
            "genuine_multi_scored_opportunities": sum(
                int(row["successfully_scored_candidate_count"]) > 1 for row in a3
            ),
            "a3_vs_a1_selection_differences": sum(
                row["a3_vs_a1_same_program"] is False for row in a3
            ),
            "audit_candidate_count": sum(int(row["audit_candidate_count"]) for row in a3),
            "content_verified_candidate_count": sum(
                int(row["content_verified_candidate_count"]) for row in a3
            ),
            "prefill_evidence_candidate_count": sum(
                int(row["prefill_evidence_candidate_count"]) for row in a3
            ),
            "complete_victim_geometry_candidate_count": sum(
                int(row["complete_victim_geometry_candidate_count"]) for row in a3
            ),
        },
        "a2": {
            "forced_decision_count": len(a2),
            "cost_known_count": sum(row["a2_cost_known"] is True for row in a2),
            "search_truncated_count": sum(row["a2_search_truncated"] is True for row in a2),
            "selected_differs_from_native_lru_count": sum(
                row["a2_selected_equals_native_lru"] is False for row in a2
            ),
            "identified_hashed_block_total": sum(
                int(row["a2_identified_hashed_blocks"] or 0) for row in a2
            ),
        },
        "claim_boundary": {
            "physical_causal_attribution": "NOT_ESTABLISHED",
            "downstream_recompute_per_decision": "NOT_ESTABLISHED",
            "cross_run_native_hash_identity": "NOT_PORTABLE",
        },
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_rows = []
    for path in sorted(output.iterdir()):
        if path.name == "sha256-manifest.txt":
            continue
        manifest_rows.append(f"{_sha256(path)}  {path.name}")
    (output / "sha256-manifest.txt").write_text("\n".join(manifest_rows) + "\n", encoding="utf-8")
    return summary
