"""Fail-closed Phase 5 candidate-exposure evaluator prototype."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence


def _events(
    rows: Sequence[Mapping[str, object]], event_type: str
) -> list[Mapping[str, object]]:
    return sorted(
        (row for row in rows if row.get("event_type") == event_type),
        key=lambda row: int(row.get("event_index", -1)),
    )


def _payload(row: Mapping[str, object], label: str) -> Mapping[str, object]:
    value = row.get("payload")
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} payload must be an object")
    return value


def _program(candidate: Mapping[str, object]) -> str:
    value = candidate.get("program_id")
    if not isinstance(value, str) or not value:
        raise ValueError("decision candidate lacks program_id")
    return value


def _unique_event_indices(events: Sequence[Mapping[str, object]]) -> None:
    indices = []
    for row in events:
        value = row.get("event_index")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("event_index must be a non-negative integer")
        indices.append(value)
    if len(indices) != len(set(indices)):
        raise ValueError("event stream contains duplicate event_index values")


def _unique_by_key(
    rows: Sequence[Mapping[str, object]],
    *,
    label: str,
    key,
) -> dict[object, Mapping[str, object]]:
    result = {}
    for row in rows:
        payload = _payload(row, label)
        identity = key(payload)
        if identity in result:
            raise ValueError(f"{label} identity is not unique")
        result[identity] = payload
    return result


def _binding_index(payload: Mapping[str, object]) -> int:
    value = payload.get("forced_release_event_index")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("decision binding has invalid forced_release_event_index")
    return value


def _decision_id(payload: Mapping[str, object], label: str) -> str:
    value = payload.get("decision_id")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} lacks decision_id")
    return value


def _finite_score(candidate: Mapping[str, object]) -> float | None:
    value = candidate.get("score")
    if value is None:
        value = candidate.get("expected_recompute")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _decision_identity(
    binding: Mapping[str, object], decision: Mapping[str, object]
) -> str:
    for field in ("frozen_decision_boundary_id", "boundary_id"):
        value = binding.get(field, decision.get(field))
        if isinstance(value, str) and value:
            return value
    raise ValueError("decision lacks a stable frozen boundary identity")


def evaluate_run_candidate_exposure(
    *, run_id: str, arm: str, events: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Summarize complete candidates, physical victims and future reuse signals."""

    _unique_event_indices(events)
    decisions = _events(events, "FORCED_RELEASE_DECISION")
    bindings = _unique_by_key(
        _events(events, "FORCED_RELEASE_DECISION_BINDING"),
        label="decision binding",
        key=_binding_index,
    )
    binding_decision_ids = [
        _decision_id(payload, "decision binding") for payload in bindings.values()
    ]
    if len(binding_decision_ids) != len(set(binding_decision_ids)):
        raise ValueError("one decision has more than one binding")
    plans = _unique_by_key(
        _events(events, "NATIVE_ENTRY_RELEASE_SELECTION_PLAN"),
        label="selection plan",
        key=lambda payload: _decision_id(payload, "selection plan"),
    )
    outcomes = _unique_by_key(
        _events(events, "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME"),
        label="physical outcome",
        key=lambda payload: _decision_id(payload, "physical outcome"),
    )
    observations = _events(events, "VLLM_NATIVE_REQUEST_OBSERVATION")
    rows = []
    stable_identities: set[str] = set()
    for ordinal, decision in enumerate(decisions, start=1):
        decision_index = int(decision.get("event_index", -1))
        payload = _payload(decision, "forced release decision")
        candidates_raw = payload.get("candidates")
        selected_raw = payload.get("selected_releases")
        if not isinstance(candidates_raw, list) or not isinstance(selected_raw, list):
            raise TypeError("forced release decision lacks candidate/selection lists")
        candidates = []
        for candidate_raw in candidates_raw:
            if not isinstance(candidate_raw, Mapping):
                raise TypeError("decision candidate must be an object")
            candidate = dict(candidate_raw)
            block_ids = candidate.get("block_ids")
            reclaimable = candidate.get("initially_reclaimable_block_ids")
            if not isinstance(block_ids, list) or not isinstance(reclaimable, list):
                raise TypeError("candidate lacks physical block inventory")
            candidates.append(candidate)
        selected_programs = tuple(_program(row) for row in selected_raw)
        candidate_programs = tuple(_program(row) for row in candidates)
        if not set(selected_programs).issubset(candidate_programs):
            raise ValueError("selected release is outside the legal candidate set")
        binding = bindings.get(decision_index)
        if binding is None:
            raise ValueError("forced release decision lacks Native binding")
        decision_id = binding.get("decision_id")
        if not isinstance(decision_id, str) or not decision_id:
            raise ValueError("decision binding lacks decision_id")
        stable_identity = _decision_identity(binding, payload)
        if stable_identity in stable_identities:
            raise ValueError("frozen decision boundary identity is not unique")
        stable_identities.add(stable_identity)
        plan = plans.get(decision_id)
        outcome = outcomes.get(decision_id)
        if plan is None or outcome is None:
            raise ValueError("bound decision lacks selection plan or physical outcome")
        selected_blocks = plan.get("selected_native_block_ids")
        if selected_blocks is None:
            selected_blocks = plan.get("selected_block_ids")
        if not isinstance(selected_blocks, list):
            raise TypeError("selection plan lacks selected block IDs")
        matched = outcome.get("matched_physical_block_ids", [])
        unmatched = outcome.get("unmatched_physical_block_ids", [])
        hashless = outcome.get("hashless_physical_block_ids", [])
        if not all(isinstance(value, list) for value in (matched, unmatched, hashless)):
            raise ValueError("physical outcome block sets are incomplete")
        later_programs = {
            str(row.get("program_id"))
            for row in observations
            if int(row.get("event_index", -1)) > decision_index
        }
        reuse_opportunities = sorted(set(candidate_programs).intersection(later_programs))
        scores = [_finite_score(candidate) for candidate in candidates]
        scored = sum(value is not None for value in scores)
        invalid_scores = sum(
            (candidate.get("score") is not None
             or candidate.get("expected_recompute") is not None)
            and value is None
            for candidate, value in zip(candidates, scores, strict=True)
        )
        complete = sum(
            bool(candidate.get("block_ids"))
            and isinstance(candidate.get("native_hash_process_id"), str)
            and bool(candidate.get("native_hash_process_id"))
            for candidate in candidates
        )
        rows.append(
            {
                "ordinal": ordinal,
                "decision_id": decision_id,
                "decision_identity": stable_identity,
                "event_index": decision_index,
                "legal_candidate_count": len(candidates),
                "multi_candidate": len(candidates) >= 2,
                "scored_candidate_count": scored,
                "invalid_score_candidate_count": invalid_scores,
                "physical_identity_complete_candidate_count": complete,
                "selected_program_ids": list(selected_programs),
                "selected_physical_block_ids": list(selected_blocks),
                "matched_physical_block_ids": list(matched),
                "unmatched_physical_block_ids": list(unmatched),
                "hashless_physical_block_ids": list(hashless),
                "downstream_reuse_opportunity_program_ids": reuse_opportunities,
                "downstream_recompute_attribution": "NOT_ESTABLISHED",
            }
        )
    return {
        "schema_version": "phase5.candidate_exposure_run.v1",
        "status": "PASS",
        "run_id": run_id,
        "arm": arm,
        "decision_count": len(rows),
        "multi_candidate_decision_count": sum(bool(row["multi_candidate"]) for row in rows),
        "decisions": rows,
    }


def compare_candidate_exposure(
    reports: Mapping[str, Mapping[str, object]], *, required_arms: Sequence[str]
) -> dict[str, object]:
    """Compare choices and victims using a shared frozen decision identity."""

    arms = tuple(required_arms)
    if set(reports) != set(arms):
        raise ValueError("candidate exposure comparison arm set mismatch")
    if any(report.get("status") != "PASS" for report in reports.values()):
        raise ValueError("candidate exposure comparison requires passing reports")
    decisions_by_arm = {}
    identities_by_arm = {}
    for arm in arms:
        rows = reports[arm].get("decisions")
        if not isinstance(rows, list):
            raise TypeError("candidate exposure report lacks decisions")
        by_identity = {}
        for row in rows:
            identity = row.get("decision_identity")
            if not isinstance(identity, str) or not identity:
                raise ValueError("candidate exposure decision lacks stable identity")
            if identity in by_identity:
                raise ValueError("candidate exposure decision identity is not unique")
            by_identity[identity] = row
        decisions_by_arm[arm] = by_identity
        identities_by_arm[arm] = frozenset(by_identity)
    identity_sets = set(identities_by_arm.values())
    if len(identity_sets) != 1:
        raise ValueError("arms expose different decision identity sets")
    aligned_identities = sorted(next(iter(identity_sets), frozenset()))
    comparison = []
    logical_divergence = 0
    physical_divergence = 0
    for identity in aligned_identities:
        logical = {
            arm: tuple(decisions_by_arm[arm][identity]["selected_program_ids"])
            for arm in arms
        }
        physical = {
            arm: tuple(decisions_by_arm[arm][identity]["selected_physical_block_ids"])
            for arm in arms
        }
        logical_differs = len(set(logical.values())) > 1
        physical_differs = len(set(physical.values())) > 1
        logical_divergence += logical_differs
        physical_divergence += physical_differs
        comparison.append(
            {
                "decision_identity": identity,
                "logical_selection_by_arm": {
                    arm: list(value) for arm, value in logical.items()
                },
                "physical_victim_set_by_arm": {
                    arm: list(value) for arm, value in physical.items()
                },
                "logical_selection_differs": logical_differs,
                "physical_victim_set_differs": physical_differs,
            }
        )
    exposure = Counter()
    for arm, rows in decisions_by_arm.items():
        exposure[f"{arm}:decisions"] = len(rows)
        exposure[f"{arm}:multi_candidate"] = sum(
            bool(row["multi_candidate"]) for row in rows.values()
        )
    return {
        "schema_version": "phase5.candidate_exposure_comparison.v1",
        "status": "PASS",
        "arm_exposure_counts": dict(sorted(exposure.items())),
        "logical_selection_divergence_count": logical_divergence,
        "physical_victim_set_divergence_count": physical_divergence,
        "comparisons": comparison,
        "downstream_recompute_attribution": "NOT_ESTABLISHED",
    }

