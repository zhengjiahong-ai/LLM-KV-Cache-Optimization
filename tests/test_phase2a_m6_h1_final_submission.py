import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
SUBMISSION = (
    ROOT
    / "docs/experiments/phase2a-m6-h1/formal-level-a-review-submission.json"
)
HANDOFF = (
    ROOT
    / "docs/experiments/phase2a-m6-h1/formal-level-a-evidence-handoff.json"
)
VERDICT = (
    ROOT / "docs/experiments/phase2a-m6-h1/formal-level-a-verdict.json"
)


def test_h1_submission_preserves_level_a_boundaries() -> None:
    submission = json.loads(SUBMISSION.read_text(encoding="utf-8"))

    assert submission["candidate_conclusion"]["candidate_outcome"] == (
        "DIAGNOSTIC_ONLY"
    )
    assert submission["candidate_conclusion"]["accepted"] is False
    assert submission["authorization_state"]["formal_verdict_pending_m1_m4_review"]
    assert not submission["authorization_state"]["level_b_runtime_claim_authorized"]
    assert submission["execution"]["successful_run_count"] == 96
    assert submission["execution"]["failed_run_count"] == 30
    assert submission["paired_level_a_result"][
        "paired_evaluable_independent_scenarios"
    ] == 29


def test_h1_handoff_binds_external_archive_without_mutating_raw_evidence() -> None:
    handoff = json.loads(HANDOFF.read_text(encoding="utf-8"))

    assert handoff["archive"]["entry_count"] == 1174
    assert handoff["archive"]["size_bytes"] == 3123160
    assert len(handoff["archive"]["sha256"]) == 64
    assert handoff["handling"]["archive_committed_to_git"] is False
    assert handoff["handling"]["failed_attempts_removed"] is False
    assert handoff["handling"]["raw_artifacts_modified"] is False


def test_h1_final_verdict_closes_experiment_without_promoting_rule() -> None:
    verdict = json.loads(VERDICT.read_text(encoding="utf-8"))

    assert verdict["decision"]["campaign_disposition"] == (
        "H1_CAMPAIGN_ACCEPTED_EXPERIMENT_CLOSED"
    )
    assert verdict["decision"]["formal_rule_verdict"] == "DIAGNOSTIC_ONLY"
    assert verdict["decision"]["h1_r1_promoted_to_proxy_candidate"] is False
    assert verdict["decision"]["supplemental_runs_required"] is False
    assert verdict["authorization_state"]["formal_h1_experiment_closed"] is True
    assert not verdict["authorization_state"][
        "level_b_runtime_validation_authorized"
    ]
    assert not verdict["authorization_state"][
        "challenger_runtime_policy_switch_authorized"
    ]
