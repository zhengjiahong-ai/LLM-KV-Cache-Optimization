"""Static/Mock gates for Phase 2I A3 Native integration.

This evaluator consumes persisted-style event dictionaries.  It never runs a
model and never treats predicted victims as physical evictions.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

EXPECTED_PRESSURE_BOUNDARIES = frozenset(
    {
        "pressure:after-round-40",
        "pressure:after-round-50",
        "pressure:after-round-55",
    }
)
PHYSICAL_OUTCOME_STATUSES = frozenset(
    {
        "PHYSICAL_EVICTION_OBSERVED",
        "PARTIAL_PHYSICAL_EVICTION_OBSERVED",
        "NO_PHYSICAL_EVICTION_OBSERVED",
        "EVIDENCE_MISSING",
    }
)


def _payload(event: Mapping[str, object]) -> Mapping[str, object]:
    value = event.get("payload")
    return value if isinstance(value, Mapping) else {}


def _events_by_type(
    events: Iterable[Mapping[str, object]], event_type: str
) -> tuple[Mapping[str, object], ...]:
    return tuple(event for event in events if event.get("event_type") == event_type)


def _finite_float(value: object) -> bool:
    return type(value) is float and math.isfinite(value)


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _candidate_key(value: object) -> tuple[str, str] | None:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or not all(isinstance(item, str) and item for item in value)
    ):
        return None
    return str(value[0]), str(value[1])


def evaluate_a3_native_preflight(
    events: Iterable[Mapping[str, object]],
    *,
    require_a1_a3_intervention: bool = True,
) -> dict[str, object]:
    """Evaluate frozen I/C/D/O gates from Native-integration evidence."""

    rows = tuple(events)
    a3_events = _events_by_type(rows, "A3_SUFFIX_RELEASE_DECISION")
    forced_events = {
        int(event["event_index"]): event
        for event in _events_by_type(rows, "FORCED_RELEASE_DECISION")
        if isinstance(event.get("event_index"), int)
    }
    binding_events = _events_by_type(rows, "FORCED_RELEASE_DECISION_BINDING")
    plans = _events_by_type(rows, "NATIVE_ENTRY_RELEASE_SELECTION_PLAN")
    pending_plans = _events_by_type(rows, "NATIVE_SELECTION_PLAN_PENDING")
    physical_outcomes = _events_by_type(
        rows, "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME"
    )
    evictions = _events_by_type(rows, "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED")
    barriers = _events_by_type(rows, "CONTROLLED_REPLAY_PRESSURE_COMPLETED")

    selections: list[Mapping[str, object]] = []
    formula_valid = True
    ordering_valid = True
    native_live_only = True
    content_valid = True
    intervention_count = 0
    intervention_decision_ids: set[str] = set()
    executed_decision_ids: set[str] = set()
    multi_candidate_decision_ids: set[str] = set()
    valid_nonfallback_multi_decision_ids: set[str] = set()
    fallback_decision_ids: set[str] = set()
    fallback_valid = True
    selected_keys_by_decision: dict[str, set[tuple[str, str]]] = {}
    a3_payload_by_id: dict[str, Mapping[str, object]] = {}
    a3_event_count_with_id = 0
    non_fallback_count = 0
    for event in a3_events:
        payload = _payload(event)
        native_live_only &= payload.get("verification_mode") == "native_live"
        native_live_only &= bool(payload.get("native_hash_process_id"))
        native_live_only &= payload.get("decision_clock_domain") == "continuum_pressure"
        native_live_only &= isinstance(payload.get("decision_event_index"), int)
        native_live_only &= payload.get("boundary_type") in {
            "CONTROLLED_PRESSURE",
            "ORDINARY_REQUEST",
            "NATIVE_DRAIN_BATCH",
        }
        native_live_only &= isinstance(payload.get("execution_context_id"), str)
        native_live_only &= bool(tuple(payload.get("request_ids") or ()))
        trace = payload.get("selection_trace")
        if payload.get("decision_id"):
            a3_event_count_with_id += 1
            decision_id = str(payload["decision_id"])
            a3_payload_by_id[decision_id] = payload
        if not isinstance(trace, (list, tuple)):
            formula_valid = False
            continue
        for raw_selection in trace:
            if not isinstance(raw_selection, Mapping):
                formula_valid = False
                continue
            selections.append(raw_selection)
            decision_id = (
                str(payload["decision_id"]) if payload.get("decision_id") else None
            )
            key = raw_selection.get("key")
            normalized_key = _candidate_key(key)
            if decision_id is not None and normalized_key is not None:
                selected_keys_by_decision.setdefault(decision_id, set()).add(
                    normalized_key
                )
            if raw_selection.get("fell_back") is True:
                if decision_id is not None:
                    fallback_decision_ids.add(decision_id)
                fallback_valid &= key == raw_selection.get("a1_key")
                continue
            non_fallback_count += 1
            intervened = raw_selection.get("key") != raw_selection.get("a1_key")
            intervention_count += int(intervened)
            if decision_id is not None:
                executed_decision_ids.add(decision_id)
                if intervened:
                    intervention_decision_ids.add(decision_id)
            audits = raw_selection.get("audits")
            if not isinstance(audits, (list, tuple)):
                formula_valid = False
                continue
            if len(audits) < 2:
                formula_valid = False
                continue
            if decision_id is not None:
                multi_candidate_decision_ids.add(decision_id)
            ordered_candidates: list[tuple[float, float, tuple[str, str], bool]] = []
            for audit in audits:
                if not isinstance(audit, Mapping):
                    formula_valid = False
                    continue
                audit_key = _candidate_key(audit.get("key"))
                score = audit.get("score")
                deadline = audit.get("deadline")
                selected = audit.get("selected")
                if (
                    audit_key is None
                    or not _finite_float(score)
                    or not _finite_float(deadline)
                    or type(selected) is not bool
                    or not _finite_float(audit.get("reuse_proxy"))
                    or not _finite_float(audit.get("prefill_reload_seconds"))
                    or not _positive_int(audit.get("suffix_blocks"))
                    or not _positive_int(audit.get("chain_length"))
                ):
                    formula_valid = False
                    ordering_valid = False
                    continue
                content_valid &= audit.get("content_verified") is True
                expected = (
                    audit["reuse_proxy"]
                    * audit["prefill_reload_seconds"]
                    * audit["suffix_blocks"]
                    / audit["chain_length"]
                )
                formula_valid &= math.isclose(
                    score, expected, rel_tol=1e-12, abs_tol=1e-12
                )
                ordered_candidates.append((score, deadline, audit_key, selected))
            if len(ordered_candidates) != len(audits):
                ordering_valid = False
            else:
                winner = min(ordered_candidates, key=lambda row: row[:3])
                marked = tuple(row for row in ordered_candidates if row[3] is True)
                ordering_valid &= normalized_key == winner[2]
                ordering_valid &= len(marked) == 1 and marked[0][2] == winner[2]
            if (
                decision_id is not None
                and formula_valid
                and content_valid
                and ordering_valid
            ):
                valid_nonfallback_multi_decision_ids.add(decision_id)

    bindings_by_id = {
        str(_payload(event).get("decision_id")): _payload(event)
        for event in binding_events
        if _payload(event).get("decision_id")
    }
    plans_by_id = {
        str(_payload(event).get("decision_id")): _payload(event)
        for event in plans
        if _payload(event).get("decision_id")
    }
    pending_by_id = {
        str(_payload(event).get("decision_id")): _payload(event)
        for event in pending_plans
        if _payload(event).get("decision_id")
    }
    outcomes_by_id = {
        str(_payload(event).get("decision_id")): _payload(event)
        for event in physical_outcomes
        if _payload(event).get("decision_id")
    }
    identifiers_unique = (
        len(a3_payload_by_id) == a3_event_count_with_id
        and len(bindings_by_id) == len(binding_events)
        and len(plans_by_id) == len(plans)
        and len(pending_by_id) == len(pending_plans)
        and len(outcomes_by_id) == len(physical_outcomes)
    )
    decision_ids = set(bindings_by_id) & set(plans_by_id)
    required_decision_ids = (
        intervention_decision_ids
        if require_a1_a3_intervention
        else executed_decision_ids & multi_candidate_decision_ids
    )
    required_decisions_joined = required_decision_ids & decision_ids
    actual_release_match_count = 0
    for decision_id in decision_ids:
        forced_index = bindings_by_id[decision_id].get("forced_release_event_index")
        forced_event = (
            forced_events.get(int(forced_index))
            if isinstance(forced_index, int)
            else None
        )
        selected_releases = (
            tuple(_payload(forced_event).get("selected_releases") or ())
            if forced_event is not None
            else ()
        )
        actual_keys = {
            (str(item.get("program_id")), str(item.get("prefix_id")))
            for item in selected_releases
            if isinstance(item, Mapping)
        }
        expected_keys = selected_keys_by_decision.get(decision_id, set())
        actual_release_match_count += int(bool(expected_keys) and expected_keys == actual_keys)
    def same_context(*payloads: Mapping[str, object]) -> bool:
        if not payloads:
            return False
        boundary_type = payloads[0].get("boundary_type")
        fields = ["execution_context_id", "boundary_type", "request_ids"]
        if boundary_type == "CONTROLLED_PRESSURE":
            fields.extend(("boundary_id", "stage_id", "pressure_request_id"))
        return all(
            all(payload.get(field) == payloads[0].get(field) for payload in payloads)
            for field in fields
        )

    decision_join_valid = (
        bool(decision_ids)
        and set(a3_payload_by_id) == decision_ids
        and set(bindings_by_id) == decision_ids
        and set(plans_by_id) == decision_ids
        and identifiers_unique
        and all(
            same_context(
                a3_payload_by_id[decision_id],
                bindings_by_id[decision_id],
                plans_by_id[decision_id],
            )
            for decision_id in decision_ids
        )
        and all(
            a3_payload_by_id[decision_id].get("decision_event_index")
            == bindings_by_id[decision_id].get("forced_release_event_index")
            for decision_id in decision_ids
        )
    )

    ordered_bindings = sorted(
        bindings_by_id.values(),
        key=lambda payload: int(payload.get("forced_release_event_index", -1)),
    )
    counter_valid = True
    forced_indexes = tuple(
        payload.get("forced_release_event_index") for payload in ordered_bindings
    )
    counter_valid &= all(isinstance(value, int) for value in forced_indexes)
    counter_valid &= len(forced_indexes) == len(set(forced_indexes))
    previous_after: int | None = None
    for payload in ordered_bindings:
        try:
            before = int(payload["forced_release_counter_before"])
            after = int(payload["forced_release_counter_after"])
            selected_count = int(payload["selected_release_count"])
            counter_valid &= after - before == int(selected_count > 0)
            if previous_after is not None:
                counter_valid &= before == previous_after
            previous_after = after
            forced_index = int(payload["forced_release_event_index"])
            forced_event = forced_events.get(forced_index)
            forced_selected = tuple(
                _payload(forced_event).get("selected_releases") or ()
            ) if forced_event is not None else ()
            counter_valid &= selected_count == len(forced_selected)
        except (KeyError, TypeError, ValueError):
            counter_valid = False

    barrier_boundaries = tuple(
        str(_payload(event).get("boundary_id")) for event in barriers
    )
    barrier_binding_valid = (
        len(barriers) == len(EXPECTED_PRESSURE_BOUNDARIES)
        and len(barrier_boundaries) == len(set(barrier_boundaries))
        and set(barrier_boundaries) == EXPECTED_PRESSURE_BOUNDARIES
    )
    for event in barriers:
        payload = _payload(event)
        bound_ids = tuple(str(value) for value in payload.get("bound_decision_ids") or ())
        bound_bindings = tuple(bindings_by_id.get(decision_id) for decision_id in bound_ids)
        all_bound_ids_resolve = all(binding is not None for binding in bound_bindings)
        expected_ids = tuple(
            decision_id
            for decision_id, plan in plans_by_id.items()
            if plan.get("boundary_type") == "CONTROLLED_PRESSURE"
            and plan.get("boundary_id") == payload.get("boundary_id")
            and plan.get("stage_id") == payload.get("stage_id")
        )
        barrier_binding_valid &= len(bound_ids) == len(set(bound_ids))
        barrier_binding_valid &= all_bound_ids_resolve
        barrier_binding_valid &= set(bound_ids) == set(expected_ids)
        barrier_binding_valid &= int(payload.get("bound_decision_count", -1)) == len(
            bound_ids
        )
        barrier_binding_valid &= int(
            payload.get("bound_forced_release_count", -1)
        ) == sum(
            int(binding.get("selected_release_count", 0) > 0)
            for binding in bound_bindings
            if binding is not None
        )

    physical_join_count = 0
    physical_join_valid = True
    matched_blocks_by_decision: dict[str, set[int]] = {}
    for event in evictions:
        payload = _payload(event)
        if payload.get("physical_attribution") != "MATCHED_PENDING_SELECTION_PLAN":
            continue
        decision_id = str(payload.get("decision_id") or "")
        block_id = payload.get("block_id")
        native_key = payload.get("native_cache_key_before")
        pending = pending_by_id.get(decision_id)
        plan = plans_by_id.get(decision_id)
        if (
            pending is None
            or plan is None
            or not isinstance(block_id, int)
            or not isinstance(native_key, str)
        ):
            physical_join_valid = False
            continue
        expected_content = {
            int(item["block_id"]): str(item["native_cache_key"])
            for item in tuple(pending.get("content_identity_by_block") or ())
            if isinstance(item, Mapping)
            and isinstance(item.get("block_id"), int)
            and isinstance(item.get("native_cache_key"), str)
        }
        context_matches = same_context(payload, pending, plan)
        legal_block = block_id in tuple(plan.get("selected_native_block_ids") or ())
        content_match = expected_content.get(block_id) == native_key
        duplicate = block_id in matched_blocks_by_decision.setdefault(decision_id, set())
        physical_join_valid &= (
            context_matches and legal_block and content_match and not duplicate
        )
        if context_matches and legal_block and content_match and not duplicate:
            matched_blocks_by_decision[decision_id].add(block_id)
            physical_join_count += 1
    for decision_id, pending in pending_by_id.items():
        expected_blocks = {
            int(value)
            for value in tuple(pending.get("selected_block_ids") or ())
        }
        physical_join_valid &= matched_blocks_by_decision.get(decision_id, set()) == expected_blocks

    physical_decision_ids = {
        decision_id
        for decision_id, outcome in outcomes_by_id.items()
        if outcome.get("status") == "PHYSICAL_EVICTION_OBSERVED"
    }
    def physical_outcome_valid(
        decision_id: str, outcome: Mapping[str, object]
    ) -> bool:
        status = outcome.get("status")
        if status not in PHYSICAL_OUTCOME_STATUSES:
            return False
        matched_values = tuple(outcome.get("matched_block_ids") or ())
        unmatched_values = tuple(outcome.get("unmatched_block_ids") or ())
        hashless_values = tuple(outcome.get("hashless_block_ids") or ())
        if not all(
            type(value) is int
            for value in (*matched_values, *unmatched_values, *hashless_values)
        ):
            return False
        matched = set(matched_values)
        unmatched = set(unmatched_values)
        hashless = set(hashless_values)
        if (
            len(matched) != len(matched_values)
            or len(unmatched) != len(unmatched_values)
            or len(hashless) != len(hashless_values)
            or matched & unmatched
            or matched & hashless
            or unmatched & hashless
        ):
            return False
        pending = pending_by_id.get(decision_id)
        plan = plans_by_id.get(decision_id)
        if plan is None:
            return False
        planned = set(plan.get("selected_native_block_ids") or ())
        expected = (
            set(pending.get("selected_block_ids") or ()) if pending is not None else set()
        )
        if status == "PHYSICAL_EVICTION_OBSERVED":
            return (
                bool(matched)
                and not unmatched
                and not hashless
                and pending is not None
                and matched == expected
                and matched <= planned
            )
        if status == "PARTIAL_PHYSICAL_EVICTION_OBSERVED":
            return (
                bool(matched)
                and bool(unmatched)
                and not hashless
                and pending is not None
                and matched | unmatched == expected
                and expected <= planned
            )
        if status == "NO_PHYSICAL_EVICTION_OBSERVED":
            if matched:
                return False
            if pending is None:
                return (
                    not unmatched
                    and bool(hashless)
                    and hashless == planned
                    and outcome.get("reason")
                    == "NATIVE_SELECTION_RETURN_CONTAINED_NO_HASHED_BLOCKS"
                )
            return not hashless and unmatched == expected and expected <= planned
        return not matched and not hashless

    physical_outcomes_valid = (
        set(outcomes_by_id) == decision_ids
        and set(pending_by_id) <= decision_ids
        and all(
        same_context(outcome, plans_by_id[decision_id])
        and physical_outcome_valid(decision_id, outcome)
        for decision_id, outcome in outcomes_by_id.items()
        )
    )
    evidence_missing_outcome_count = sum(
        outcome.get("status") == "EVIDENCE_MISSING"
        for outcome in outcomes_by_id.values()
    )
    required_physical_observed = bool(required_decision_ids & physical_decision_ids)

    gates = {
        "I": {
            "status": "PASS" if a3_events and native_live_only else "FAIL",
            "native_live_only": native_live_only,
            "a3_decision_event_count": len(a3_events),
        },
        "C": {
            "status": (
                "PASS"
                if valid_nonfallback_multi_decision_ids
                and content_valid
                and formula_valid
                and ordering_valid
                else "FAIL"
            ),
            "content_verified_non_fallback_count": non_fallback_count,
            "valid_nonfallback_multi_candidate_decision_count": len(
                valid_nonfallback_multi_decision_ids
            ),
            "formula_recomputed": formula_valid,
            "ordering_recomputed": ordering_valid,
        },
        "D": {
            "status": (
                "PASS"
                if required_decision_ids
                and required_decisions_joined == required_decision_ids
                and actual_release_match_count == len(decision_ids)
                and formula_valid
                and ordering_valid
                and fallback_valid
                and decision_join_valid
                else "FAIL"
            ),
            "a1_a3_intervention_count": intervention_count,
            "require_a1_a3_intervention": require_a1_a3_intervention,
            "executed_non_fallback_decision_count": len(executed_decision_ids),
            "multi_candidate_decision_count": len(multi_candidate_decision_ids),
            "joined_required_decision_count": len(required_decisions_joined),
            "actual_release_match_count": actual_release_match_count,
            "fallback_decision_count": len(fallback_decision_ids),
            "fallback_selection_valid": fallback_valid,
            "decision_join_valid": decision_join_valid,
        },
        "O": {
            "status": (
                "PASS"
                if decision_join_valid
                and counter_valid
                and barrier_binding_valid
                and physical_join_valid
                and physical_outcomes_valid
                and evidence_missing_outcome_count == 0
                and required_physical_observed
                else "FAIL"
            ),
            "counter_chain_valid": counter_valid,
            "barrier_binding_valid": barrier_binding_valid,
            "physical_eviction_join_count": physical_join_count,
            "physical_eviction_join_valid": physical_join_valid,
            "physical_outcomes_valid": physical_outcomes_valid,
            "evidence_missing_outcome_count": evidence_missing_outcome_count,
            "required_physical_observed": required_physical_observed,
            "no_physical_eviction_decision_count": sum(
                outcome.get("status") == "NO_PHYSICAL_EVICTION_OBSERVED"
                for outcome in outcomes_by_id.values()
            ),
        },
    }
    return {
        "schema_version": "phase2i.a3_native_static_preflight.v1",
        "status": (
            "PASS_STATIC_PREFLIGHT"
            if all(gate["status"] == "PASS" for gate in gates.values())
            else "FAIL_CLOSED"
        ),
        "gates": gates,
        "claim_scope": "CPU/MOCK_STATIC_ONLY_NOT_GPU_NATIVE_OUTCOME",
    }
