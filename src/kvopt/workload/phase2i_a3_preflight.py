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
    evictions = _events_by_type(rows, "VLLM_NATIVE_HASHED_CACHE_ENTRY_EVICTED")
    barriers = _events_by_type(rows, "CONTROLLED_REPLAY_PRESSURE_COMPLETED")

    selections: list[Mapping[str, object]] = []
    formula_valid = True
    native_live_only = True
    content_valid = True
    intervention_count = 0
    intervention_decision_ids: set[str] = set()
    selected_key_by_decision: dict[str, tuple[str, str]] = {}
    non_fallback_count = 0
    for event in a3_events:
        payload = _payload(event)
        native_live_only &= payload.get("verification_mode") == "native_live"
        native_live_only &= bool(payload.get("native_hash_process_id"))
        native_live_only &= payload.get("decision_clock_domain") == "continuum_pressure"
        native_live_only &= isinstance(payload.get("decision_event_index"), int)
        trace = payload.get("selection_trace")
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
            if intervened and payload.get("decision_id"):
                decision_id = str(payload["decision_id"])
                intervention_decision_ids.add(decision_id)
                key = raw_selection.get("key")
                if isinstance(key, (list, tuple)) and len(key) == 2:
                    selected_key_by_decision[decision_id] = (str(key[0]), str(key[1]))
            audits = raw_selection.get("audits")
            if not isinstance(audits, (list, tuple)):
                formula_valid = False
                continue
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
    decision_ids = set(bindings_by_id) & set(plans_by_id)
    intervened_decisions_joined = intervention_decision_ids & decision_ids
    actual_release_match_count = 0
    for decision_id in intervened_decisions_joined:
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
        actual_release_match_count += int(
            selected_key_by_decision.get(decision_id) in actual_keys
        )
    decision_join_valid = bool(decision_ids) and all(
        bindings_by_id[decision_id].get("pressure_request_id")
        == plans_by_id[decision_id].get("pressure_request_id")
        for decision_id in decision_ids
    )
    counter_valid = all(
        int(payload.get("forced_release_counter_after", -1))
        >= int(payload.get("forced_release_counter_before", -1))
        for decision_id, payload in bindings_by_id.items()
        if decision_id in plans_by_id
    )
    barrier_binding_valid = bool(barriers) and all(
        int(_payload(event).get("bound_decision_count", 0))
        == len(tuple(_payload(event).get("bound_decision_ids") or ()))
        and int(_payload(event).get("bound_forced_release_count", -1))
        == sum(
            int(bindings_by_id.get(str(decision_id), {}).get("selected_release_count", 0) > 0)
            for decision_id in tuple(_payload(event).get("bound_decision_ids") or ())
        )
        for event in barriers
    )
    physical_join_count = sum(
        1
        for event in evictions
        if _payload(event).get("decision_id") in decision_ids
        and _payload(event).get("native_cache_key_before")
    )

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
                if intervention_count
                and intervened_decisions_joined
                and actual_release_match_count == len(intervened_decisions_joined)
                and formula_valid
                and decision_join_valid
                else "FAIL"
            ),
            "a1_a3_intervention_count": intervention_count,
            "joined_intervention_count": len(intervened_decisions_joined),
            "actual_release_match_count": actual_release_match_count,
            "decision_join_valid": decision_join_valid,
        },
        "O": {
            "status": (
                "PASS"
                if decision_join_valid
                and counter_valid
                and barrier_binding_valid
                and physical_join_count
                else "FAIL"
            ),
            "counter_chain_valid": counter_valid,
            "barrier_binding_valid": barrier_binding_valid,
            "physical_eviction_join_count": physical_join_count,
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
