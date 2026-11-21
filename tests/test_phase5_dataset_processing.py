from __future__ import annotations

from pathlib import Path

from kvopt.workload.phase5_dataset_processing import (
    build_collection_summary,
    load_normalized_trace,
    load_token_materializations,
    qualify_existing_session,
)


def test_loaders_revalidate_serialized_trace_and_tokens() -> None:
    source = Path(
        "artifacts/phase5-swe-acquisition-processed-v1/sessions/"
        "phase5:swe:astropy__astropy-7606:session:1"
    )
    if not source.exists():
        return
    trace = load_normalized_trace(source / "normalized-trace.json")
    tokens = load_token_materializations(source / "token-materialization.json")
    assert trace.session_id == source.name
    assert len(tokens) == len(trace.turns)


def test_collection_summary_does_not_select_cohort() -> None:
    reports = [
        {
            "status": "QUALIFIED",
            "terminal_class": "RIGHT_CENSORED",
            "failed_rules": [],
            "qualification_sha256": "a" * 64,
        },
        {
            "status": "EXCLUDED",
            "terminal_class": "EXCLUDED",
            "failed_rules": ["Q6_CONTEXT_AND_EXACT_TOKENS"],
            "qualification_sha256": "b" * 64,
        },
    ]
    result = build_collection_summary(
        reports=reports,
        protocol_sha256="c" * 64,
        qualification_contract_sha256="d" * 64,
    )
    assert result["status_counts"] == {"EXCLUDED": 1, "QUALIFIED": 1}
    assert result["status_terminal_class_counts"] == {
        "EXCLUDED::EXCLUDED": 1,
        "QUALIFIED::RIGHT_CENSORED": 1,
    }
    assert result["formal_cohort_selected"] is False
    assert result["gpu_execution_authorized"] is False
    assert len(result["collection_summary_sha256"]) == 64


def test_terminal_adjudication_excludes_infrastructure_failure() -> None:
    source = Path(
        "artifacts/phase5-swe-acquisition-processed-v1/sessions/"
        "phase5:swe:django__django-13401:session:1"
    )
    if not source.exists():
        return
    report = qualify_existing_session(
        session_directory=source,
        protocol_sha256="a" * 64,
        qualification_contract_sha256="b" * 64,
        terminal_adjudication={source.name: "INFRASTRUCTURE_FAILURE:JobTimeoutError"},
        terminal_adjudication_sha256="c" * 64,
    )
    assert report["status"] == "EXCLUDED"
    assert report["terminal_class"] == "EXCLUDED"
    assert report["checks"]["Q5_TERMINAL_OR_CENSOR"] is False
