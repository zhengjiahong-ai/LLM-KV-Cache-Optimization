import json
from pathlib import Path

SUBMISSION = (
    Path(__file__).parents[1]
    / "docs/experiments/phase2a-m6-h2/final-remaining-measurements-review-submission.json"
)
HANDOFF = (
    Path(__file__).parents[1]
    / "docs/experiments/phase2a-m6-h2/final-evidence-handoff.json"
)


def test_h2_final_submission_keeps_review_and_b1_gates_closed() -> None:
    submission = json.loads(SUBMISSION.read_text())

    assert submission["candidate_status_summary"] == {
        "M1": "PASS_PENDING_REVIEW",
        "M2": "PASS",
        "M3": "PASS",
        "M4": "FAIL_PENDING_REVIEW",
        "aggregate_consequence": "NOT_ALL_FOUR_PASS_B1_REMAINS_CLOSED",
    }
    assert not submission["authorization_state"]["b1_authorized"]
    assert submission["authorization_state"]["formal_verdict_pending_m1_m4_review"]
    assert submission["m1"]["formal_run_count"] == 187
    assert submission["m4"]["formal_run_count"] == 264
    assert submission["m4"]["supporting_cell_count"] == 0
    assert submission["m4"]["no_resolved_headroom_cell_count"] == 12
    assert submission["excluded_attempts"][0]["formal_statistics_included"] is False


def test_h2_final_handoff_binds_external_archive() -> None:
    handoff = json.loads(HANDOFF.read_text())

    assert handoff["archive"]["entry_count"] == 3798
    assert handoff["archive"]["size_bytes"] == 72866748
    assert len(handoff["archive"]["sha256"]) == 64
    assert handoff["handling"]["archive_committed_to_git"] is False
    assert handoff["handling"]["raw_artifacts_modified"] is False
