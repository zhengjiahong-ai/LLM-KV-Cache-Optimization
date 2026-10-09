import hashlib
import json
from pathlib import Path

from kvopt.costaware.h1_seal import seal_h1_level_a_result


def _write(path: Path, payload: dict[str, object]) -> str:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_seal_binds_inputs_and_preserves_diagnostic_outcome(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign.json"
    execution = tmp_path / "execution.json"
    analysis = tmp_path / "analysis.json"
    campaign_sha = _write(
        campaign,
        {
            "campaign_id": "phase2a-h1-independent-holdout-v2",
            "formal_h1_outcome_execution_authorized": True,
            "execution_code_commit": "abc123",
        },
    )
    execution_sha = _write(
        execution,
        {"campaign_id": "phase2a-h1-independent-holdout-v2"},
    )
    _write(
        analysis,
        {
            "campaign_id": "phase2a-h1-independent-holdout-v2",
            "campaign_sha256": campaign_sha,
            "execution_summary_sha256": execution_sha,
            "acceptance_verdict": {"level": "DIAGNOSTIC_ONLY"},
        },
    )

    seal_path = seal_h1_level_a_result(
        analysis_path=analysis,
        campaign_path=campaign,
        execution_summary_path=execution,
        output_dir=tmp_path / "sealed",
        analysis_git_sha="def456",
    )

    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    provenance = json.loads(
        (seal_path.parent / "provenance.json").read_text(encoding="utf-8")
    )
    assert seal["candidate_outcome"] == "DIAGNOSTIC_ONLY"
    assert seal["formal_verdict_pending_m1_m4_review"] is True
    assert seal["level_b_runtime_claim_authorized"] is False
    assert provenance["failed_runs_preserved"] is True
    assert provenance["analysis_git_sha"] == "def456"
