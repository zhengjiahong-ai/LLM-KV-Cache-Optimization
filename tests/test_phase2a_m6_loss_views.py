from dataclasses import replace

from kvopt.profiling.datasets import DecisionCandidateRow
from kvopt.profiling.decision_outcomes import DecisionOutcomeRow
from kvopt.profiling.loss_views import build_loss_view_tables
from kvopt.profiling.runtime_evidence import RequestRuntimeEvidenceRow


def _candidate(program_id: str, *, selected: bool) -> DecisionCandidateRow:
    return DecisionCandidateRow(
        run_id="run-1",
        decision_event_index=10,
        source_event_index=10,
        candidate_position=0,
        program_id=program_id,
        prefix_id=f"prefix-{program_id}",
        selected=selected,
        release_order=1 if selected else None,
        retention_deadline_timestamp=20.0,
        waiting_followup=True,
        block_ids=(1, 2),
        block_count=2,
        initially_reclaimable_block_ids=(),
        initially_reclaimable_block_count=0,
        next_tool_type="search",
        elapsed_since_ttl_decision_seconds=2.0,
        prefill_reload_seconds=4.0 if program_id == "a" else 1.0,
        eta=3.0,
        queue_delay_t_seconds=0.5,
    )


def _outcome(program_id: str, *, selected: bool) -> DecisionOutcomeRow:
    returned = program_id == "a"
    return DecisionOutcomeRow(
        run_id="run-1",
        decision_event_index=10,
        program_id=program_id,
        prefix_id=f"prefix-{program_id}",
        selected=selected,
        return_request_id="return-a" if returned else None,
        return_arrival_event_index=20 if returned else None,
        return_arrival_timestamp=8.0 if returned else None,
        return_arrival_clock_domain="runtime" if returned else None,
        returned_after_decision=returned,
        event_distance_to_return=10 if returned else None,
        observed_time_to_return_seconds=3.0 if returned else None,
        observed_time_to_return_status="available" if returned else "no_return",
        analysis_horizon_seconds=5.0,
        observed_returned_within_horizon=returned,
        observed_return_horizon_status="available" if returned else "no_return",
        observed_horizon_margin_seconds=-2.0 if returned else None,
        planned_decision_anchor_offset_seconds=1.0,
        planned_return_offset_seconds=4.0 if returned else None,
        planned_time_to_return_seconds=3.0 if returned else None,
        planned_time_to_return_status=(
            "available" if returned else "no_planned_return"
        ),
        planned_returned_within_horizon=returned,
        planned_return_horizon_status=(
            "available" if returned else "no_planned_return"
        ),
        return_prefix_snapshot_event_index=None,
        same_prefix_reobserved=None,
        physical_eviction_event_indexes=(15,) if selected else (),
        physical_eviction_count=1 if selected else 0,
        physical_eviction_match_status=(
            "block_slot_proxy" if selected else "none_observed"
        ),
    )


def _runtime_evidence(*, recomputed_tokens: int) -> RequestRuntimeEvidenceRow:
    return RequestRuntimeEvidenceRow(
        run_id="run-1",
        request_id="return-a",
        program_id="a",
        kind="turn",
        observation_event_index=30,
        native_request_id="native-return-a",
        availability="AVAILABLE",
        unavailable_reason=None,
        native_prompt_tokens=33,
        native_cached_prefix_tokens=32 - recomputed_tokens,
        native_apc_block_hashes=("01" * 32, "02" * 32),
        native_hash_block_size=16,
        native_hash_process_id="engine-1",
        native_hash_function="sha256",
        eligible_prefix_tokens=32,
        actual_prefill_tokens=1 + recomputed_tokens,
        observed_recomputed_tokens=recomputed_tokens,
        apc_outcome="FULL_HIT" if recomputed_tokens == 0 else "PARTIAL_HIT",
        invariant_status="valid",
        native_clock_domain="engine_core_monotonic",
        native_queued_timestamp=1.0,
        native_scheduler_admission_timestamp=1.1,
        native_first_token_timestamp=1.4,
        native_queue_delay_seconds=0.1,
        native_queue_delay_status="available",
        native_prefill_to_first_token_seconds=0.3,
        native_prefill_to_first_token_status="available",
        isolated_native_prefill_elapsed_seconds=0.25,
        isolated_native_prefill_elapsed_status="available",
        backend_submission_timestamp=2.0,
        backend_completion_timestamp=2.5,
        backend_service_e2e_seconds=0.5,
        backend_service_e2e_status="available",
    )


def test_loss_views_only_send_fully_comparable_proxy_to_regret() -> None:
    tables = build_loss_view_tables(
        (_candidate("a", selected=True), _candidate("b", selected=False)),
        (_outcome("a", selected=True), _outcome("b", selected=False)),
    )
    gates = {row.loss_view: row for row in tables.availability}

    assert gates["planned_return_weighted_prefill_proxy"].usable_for_regret
    assert not gates[
        "observed_return_weighted_prefill_proxy_sensitivity"
    ].usable_for_regret
    assert not gates["observed_physical_eviction_blocks"].usable_for_regret
    assert not gates["observed_recomputed_tokens"].usable_for_regret
    assert len(tables.comparable_losses) == 2
    assert tables.loss_spreads[0].loss_spread == 4.0
    assert len(tables.decision_regret) == 1
    assert tables.decision_regret[0].absolute_regret == 4.0


def test_loss_views_preserve_physical_and_recompute_missingness() -> None:
    tables = build_loss_view_tables(
        (_candidate("a", selected=True), _candidate("b", selected=False)),
        (_outcome("a", selected=True), _outcome("b", selected=False)),
    )
    by_view_and_program = {
        (row.loss_view, row.program_id): row for row in tables.evidence
    }

    selected_physical = by_view_and_program[
        ("observed_physical_eviction_blocks", "a")
    ]
    unselected_physical = by_view_and_program[
        ("observed_physical_eviction_blocks", "b")
    ]
    recompute = by_view_and_program[("observed_recomputed_tokens", "a")]

    assert selected_physical.loss == 1.0
    assert selected_physical.availability == "available"
    assert unselected_physical.loss is None
    assert (
        unselected_physical.unavailable_reason
        == "unselected_counterfactual_not_observed"
    )
    assert recompute.loss is None
    assert recompute.unavailable_reason == (
        "return_request_runtime_observation_missing"
    )


def test_selected_return_uses_direct_runtime_recompute_evidence() -> None:
    tables = build_loss_view_tables(
        (_candidate("a", selected=True), _candidate("b", selected=False)),
        (_outcome("a", selected=True), _outcome("b", selected=False)),
        (_runtime_evidence(recomputed_tokens=16),),
    )
    recompute = {
        row.program_id: row
        for row in tables.evidence
        if row.loss_view == "observed_recomputed_tokens"
    }

    assert recompute["a"].loss == 16.0
    assert recompute["a"].availability == "available"
    assert recompute["a"].source_event_indexes == (10, 30)
    assert recompute["b"].loss is None
    assert recompute["b"].unavailable_reason == (
        "unselected_counterfactual_not_observed"
    )


def test_ambiguous_block_reuse_is_not_treated_as_physical_loss() -> None:
    selected_outcome = replace(
        _outcome("a", selected=True),
        physical_eviction_event_indexes=(),
        physical_eviction_count=0,
        physical_eviction_match_status="ambiguous_block_reuse",
    )
    tables = build_loss_view_tables(
        (_candidate("a", selected=True), _candidate("b", selected=False)),
        (selected_outcome, _outcome("b", selected=False)),
    )

    physical = next(
        row
        for row in tables.evidence
        if row.loss_view == "observed_physical_eviction_blocks"
        and row.program_id == "a"
    )
    assert physical.loss is None
    assert physical.unavailable_reason == "ambiguous_block_slot_reuse"


def test_logical_proxy_ignores_return_outside_horizon() -> None:
    late_outcome = replace(
        _outcome("a", selected=True),
        planned_returned_within_horizon=False,
    )
    tables = build_loss_view_tables(
        (_candidate("a", selected=True), _candidate("b", selected=False)),
        (late_outcome, _outcome("b", selected=False)),
    )

    proxy = next(
        row
        for row in tables.evidence
        if row.loss_view == "planned_return_weighted_prefill_proxy"
        and row.program_id == "a"
    )
    assert proxy.loss == 0.0
    assert proxy.availability == "available"


def test_logical_proxy_rejects_unknown_horizon_membership() -> None:
    unknown_outcome = replace(
        _outcome("a", selected=True),
        planned_returned_within_horizon=None,
        planned_return_horizon_status="pressure_anchor_unavailable",
    )
    tables = build_loss_view_tables(
        (_candidate("a", selected=True), _candidate("b", selected=False)),
        (unknown_outcome, _outcome("b", selected=False)),
    )

    proxy = next(
        row
        for row in tables.evidence
        if row.loss_view == "planned_return_weighted_prefill_proxy"
        and row.program_id == "a"
    )
    gate = next(
        row
        for row in tables.availability
        if row.loss_view == "planned_return_weighted_prefill_proxy"
    )
    assert proxy.loss is None
    assert proxy.unavailable_reason == (
        "return_horizon_pressure_anchor_unavailable"
    )
    assert not gate.usable_for_regret
