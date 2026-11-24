from __future__ import annotations

from dataclasses import replace

from kvopt.workload.phase5_turn_sensitivity import (
    SessionRow,
    analyze_sensitivity,
    build_analysis,
    classify_for_cap,
)


def _row(
    *,
    task: str = "task-1",
    turns: int = 6,
    terminal: str = "NATURAL_COMPLETION",
    prompt_max: int = 1000,
    q1: bool = True,
) -> SessionRow:
    counts = tuple(range(100, 100 + turns))
    requests = tuple(f"{task}:turn:{index}" for index in range(1, turns + 1))
    return SessionRow(
        source_stratum="SWE",
        acquisition_origin="PHASE5_NEW_ACQUISITION",
        task_id=task,
        program_id=task,
        session_id=f"session:{task}",
        trace_id=f"trace:{task}",
        raw_run_identity=f"PRIMARY:{task}:hash",
        attempt_source="PRIMARY",
        raw_run_path=f"raw/{task}/run.json",
        raw_run_sha256="a" * 64,
        raw_sidecar_path=f"raw/{task}/acquisition-sidecar.json",
        raw_sidecar_sha256="1" * 64,
        adapted_record_path=f"adapted/{task}.json",
        adapted_record_sha256="2" * 64,
        normalized_trace_path=f"processed/{task}/normalized-trace.json",
        normalized_trace_sha256="b" * 64,
        token_materialization_path=f"processed/{task}/token-materialization.json",
        token_materialization_sha256="c" * 64,
        qualification_path=f"processed/{task}/qualification.json",
        qualification_sha256="d" * 64,
        source_revision="e" * 40,
        acquisition_config_path="configs/acquisition.json",
        acquisition_config_sha256="f" * 64,
        execution_step_limit=100,
        turn_count=turns,
        request_id_sequence=requests,
        prompt_token_counts=counts,
        prompt_token_minimum=min(counts),
        prompt_token_maximum=prompt_max,
        prompt_token_total=sum(counts),
        prompt_token_first=counts[0],
        prompt_token_last=counts[-1],
        adjacent_prefix_pair_count=max(0, turns - 1),
        adjacent_prefix_lcp_counts=(100,) * max(0, turns - 1),
        adjacent_prefix_lcp_total=100 * max(0, turns - 1),
        adjacent_prefix_lcp_mean=100.0 if turns > 1 else 0.0,
        adjacent_prefix_lcp_maximum=100 if turns > 1 else 0,
        tool_call_count=turns,
        tool_wait_seconds_total=float(turns),
        tool_wait_seconds_maximum=1.0,
        inter_turn_gap_seconds_total=float(max(0, turns - 1)),
        inter_turn_gap_seconds_maximum=1.0,
        session_duration_seconds=float(turns),
        raw_exit_status="Submitted",
        terminal_class=terminal,
        right_censored=terminal == "STEP_LIMIT_RIGHT_CENSORED",
        q1=q1,
        q2=True,
        q3=True,
        q4=True,
        q5=True,
        q6=4 <= turns <= 16,
        q7=True,
        q8=True,
        q9=True,
        failed_rules=() if q1 else ("Q1_COMPLETE_PAYLOAD",),
        failure_reason=None if terminal == "NATURAL_COMPLETION" else terminal,
    )


def test_cap_classification_keeps_terminal_classes_distinct() -> None:
    natural = _row()
    censored = replace(
        _row(task="censored", turns=100),
        terminal_class="STEP_LIMIT_RIGHT_CENSORED",
        right_censored=True,
    )
    context = replace(
        _row(task="context"), terminal_class="CONTEXT_LIMIT_FAILURE"
    )
    infrastructure = replace(
        _row(task="infra"), terminal_class="INFRASTRUCTURE_FAILURE"
    )

    assert classify_for_cap(natural, 16) == "RETAINED"
    assert classify_for_cap(censored, 16) == "EXCLUDED_ABOVE_TURN_CAP"
    assert classify_for_cap(censored, 100) == "RETAINED"
    assert classify_for_cap(context, 100) == "EXCLUDED_CONTEXT_LIMIT_FAILURE"
    assert classify_for_cap(infrastructure, 100) == "EXCLUDED_INFRASTRUCTURE_FAILURE"


def test_context_and_other_qualification_fail_closed() -> None:
    assert (
        classify_for_cap(_row(prompt_max=32641), None)
        == "EXCLUDED_CONTEXT_PROMPT_LIMIT"
    )
    assert classify_for_cap(_row(q1=False), None) == "EXCLUDED_OTHER_Q1_Q9"
    assert classify_for_cap(_row(turns=3), None) == "EXCLUDED_BELOW_MIN_TURNS"


def test_sensitivity_includes_empty_bfcl_stratum_and_group_upper_bound() -> None:
    rows = [_row(task=f"task-{index}") for index in range(8)]
    report = analyze_sensitivity(rows)
    no_cap = report["caps"][-1]
    swe = next(row for row in no_cap["by_stratum"] if row["source_stratum"] == "SWE")
    bfcl = next(
        row for row in no_cap["by_stratum"] if row["source_stratum"] == "BFCL"
    )
    assert swe["retained_sessions"] == 8
    assert swe["group_count_upper_bound"] == 2
    assert bfcl["observed_sessions"] == 0
    assert bfcl["retained_fraction"] is None


def test_analysis_does_not_treat_turns_as_independent_units() -> None:
    rows = [_row(task=f"task-{index}", turns=20) for index in range(4)]
    report = build_analysis(
        rows=rows,
        acquisition_metadata={"attempt_count": 4, "deduplication_rule": "test"},
    )
    assert report["long_session_research_proxies"]["session_count_above_16"] == 4
    assert report["sensitivity"]["caps"][-1]["by_stratum"][1][
        "group_count_upper_bound"
    ] == 1
    assert report["recommendation"]["decision"] == "REMOVE_ADDITIONAL_PROTOCOL_TURN_CAP"
