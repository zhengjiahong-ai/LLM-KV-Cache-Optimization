"""Static/Mock gates for Phase 2I A3 Native integration.

This evaluator consumes persisted-style event dictionaries.  It never runs a
model and never treats predicted victims as physical evictions.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping


def _payload(event: Mapping[str, object]) -> Mapping[str, object]:
    value = event.get("payload")
    return value if isinstance(value, Mapping) else {}


def _events_by_type(
    events: Iterable[Mapping[str, object]], event_type: str
) -> tuple[Mapping[str, object], ...]:
    return tuple(event for event in events if event.get("event_type") == event_type)


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
    evictions = _events_by_type(rows, "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED")
    barriers = _events_by_type(rows, "CONTROLLED_REPLAY_PRESSURE_COMPLETED")

    selections: list[Mapping[str, object]] = []
    formula_valid = True
    native_live_only = True
    content_valid = True
    intervention_count = 0
    intervention_decision_ids: set[str] = set()
    executed_decision_ids: set[str] = set()
    multi_candidate_decision_ids: set[str] = set()
    selected_keys_by_decision: dict[str, set[tuple[str, str]]] = {}
    a3_payload_by_id: dict[str, Mapping[str, object]] = {}
    pressure_a3_decision_ids: set[str] = set()
    pressure_a3_event_count = 0
    non_fallback_count = 0
    for event in a3_events:
        payload = _payload(event)
        native_live_only &= payload.get("verification_mode") == "native_live"
        native_live_only &= bool(payload.get("native_hash_process_id"))
        native_live_only &= payload.get("decision_clock_domain") == "continuum_pressure"
        native_live_only &= isinstance(payload.get("decision_event_index"), int)
        trace = payload.get("selection_trace")
        if payload.get("pressure_request_id") and payload.get("decision_id"):
            pressure_a3_event_count += 1
            decision_id = str(payload["decision_id"])
            pressure_a3_decision_ids.add(decision_id)
            a3_payload_by_id[decision_id] = payload
        if not isinstance(trace, (list, tuple)):
            formula_valid = False
            continue
        for raw_selection in trace:
            if not isinstance(raw_selection, Mapping):
                formula_valid = False
                continue
            selections.append(raw_selection)
            if raw_selection.get("fell_back") is True:
                continue
            non_fallback_count += 1
            intervened = raw_selection.get("key") != raw_selection.get("a1_key")
            intervention_count += int(intervened)
            if payload.get("decision_id"):
                decision_id = str(payload["decision_id"])
                executed_decision_ids.add(decision_id)
                if intervened:
                    intervention_decision_ids.add(decision_id)
                key = raw_selection.get("key")
                if isinstance(key, (list, tuple)) and len(key) == 2:
                    selected_keys_by_decision.setdefault(decision_id, set()).add(
                        (str(key[0]), str(key[1]))
                    )
            audits = raw_selection.get("audits")
            if not isinstance(audits, (list, tuple)):
                formula_valid = False
                continue
            if payload.get("decision_id") and len(audits) >= 2:
                multi_candidate_decision_ids.add(str(payload["decision_id"]))
            for audit in audits:
                if not isinstance(audit, Mapping) or audit.get("score") is None:
                    formula_valid = False
                    continue
                content_valid &= audit.get("content_verified") is True
                try:
                    expected = (
                        float(audit["reuse_proxy"])
                        * float(audit["prefill_reload_seconds"])
                        * int(audit["suffix_blocks"])
                        / int(audit["chain_length"])
                    )
                    formula_valid &= math.isclose(
                        float(audit["score"]), expected, rel_tol=1e-12, abs_tol=1e-12
                    )
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    formula_valid = False

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
    identifiers_unique = (
        len(a3_payload_by_id) == pressure_a3_event_count
        and len(bindings_by_id) == len(binding_events)
        and len(plans_by_id) == len(plans)
        and len(pending_by_id) == len(pending_plans)
    )
    decision_ids = set(bindings_by_id) & set(plans_by_id) & set(pending_by_id)
    required_decision_ids = (
        intervention_decision_ids
        if require_a1_a3_intervention
        else executed_decision_ids & multi_candidate_decision_ids
    )
    required_decisions_joined = required_decision_ids & decision_ids
    actual_release_match_count = 0
    for decision_id in required_decisions_joined:
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
        actual_release_match_count += int(bool(expected_keys) and expected_keys <= actual_keys)
    context_fields = ("boundary_id", "stage_id", "pressure_request_id")
    decision_join_valid = (
        bool(decision_ids)
        and pressure_a3_decision_ids == decision_ids
        and identifiers_unique
        and all(
            all(
                a3_payload_by_id[decision_id].get(field)
                == bindings_by_id[decision_id].get(field)
                == plans_by_id[decision_id].get(field)
                == pending_by_id[decision_id].get(field)
                for field in context_fields
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

    barrier_binding_valid = bool(barriers)
    for event in barriers:
        payload = _payload(event)
        bound_ids = tuple(str(value) for value in payload.get("bound_decision_ids") or ())
        expected_ids = tuple(
            decision_id
            for decision_id, binding in bindings_by_id.items()
            if binding.get("boundary_id") == payload.get("boundary_id")
            and binding.get("stage_id") == payload.get("stage_id")
        )
        barrier_binding_valid &= len(bound_ids) == len(set(bound_ids))
        barrier_binding_valid &= set(bound_ids) == set(expected_ids)
        barrier_binding_valid &= int(payload.get("bound_decision_count", -1)) == len(
            bound_ids
        )
        barrier_binding_valid &= int(
            payload.get("bound_forced_release_count", -1)
        ) == sum(
            int(bindings_by_id[decision_id].get("selected_release_count", 0) > 0)
            for decision_id in bound_ids
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
        same_context = all(
            payload.get(field) == pending.get(field) == plan.get(field)
            for field in context_fields
        )
        legal_block = block_id in tuple(plan.get("selected_native_block_ids") or ())
        content_match = expected_content.get(block_id) == native_key
        duplicate = block_id in matched_blocks_by_decision.setdefault(decision_id, set())
        physical_join_valid &= same_context and legal_block and content_match and not duplicate
        if same_context and legal_block and content_match and not duplicate:
            matched_blocks_by_decision[decision_id].add(block_id)
            physical_join_count += 1
    for decision_id in decision_ids:
        expected_blocks = {
            int(value)
            for value in tuple(
                pending_by_id[decision_id].get("selected_block_ids") or ()
            )
        }
        physical_join_valid &= matched_blocks_by_decision.get(decision_id, set()) == expected_blocks

    gates = {
        "I": {
            "status": "PASS" if a3_events and native_live_only else "FAIL",
            "native_live_only": native_live_only,
            "a3_decision_event_count": len(a3_events),
        },
        "C": {
            "status": (
                "PASS" if non_fallback_count and content_valid and formula_valid else "FAIL"
            ),
            "content_verified_non_fallback_count": non_fallback_count,
            "formula_recomputed": formula_valid,
        },
        "D": {
            "status": (
                "PASS"
                if required_decision_ids
                and required_decisions_joined == required_decision_ids
                and actual_release_match_count == len(required_decisions_joined)
                and formula_valid
                and decision_join_valid
                else "FAIL"
            ),
            "a1_a3_intervention_count": intervention_count,
            "require_a1_a3_intervention": require_a1_a3_intervention,
            "executed_non_fallback_decision_count": len(executed_decision_ids),
            "multi_candidate_decision_count": len(multi_candidate_decision_ids),
            "joined_required_decision_count": len(required_decisions_joined),
            "actual_release_match_count": actual_release_match_count,
            "decision_join_valid": decision_join_valid,
        },
        "O": {
            "status": (
                "PASS"
                if decision_join_valid
                and counter_valid
                and barrier_binding_valid
                and physical_join_valid
                and physical_join_count
                else "FAIL"
            ),
            "counter_chain_valid": counter_valid,
            "barrier_binding_valid": barrier_binding_valid,
            "physical_eviction_join_count": physical_join_count,
            "physical_eviction_join_valid": physical_join_valid,
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
