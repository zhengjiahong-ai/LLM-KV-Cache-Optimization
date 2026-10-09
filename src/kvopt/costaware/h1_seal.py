"""Seal an authorized H1 Level-A result for independent review."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object: {path}")
    return payload


def _write(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def seal_h1_level_a_result(
    *,
    analysis_path: Path,
    campaign_path: Path,
    execution_summary_path: Path,
    output_dir: Path,
    analysis_git_sha: str,
) -> Path:
    """Create immutable review files without modifying any raw artifact."""
    analysis = _load(analysis_path)
    campaign = _load(campaign_path)
    execution = _load(execution_summary_path)
    campaign_id = "phase2a-h1-independent-holdout-v2"
    if analysis.get("campaign_id") != campaign_id:
        raise ValueError("analysis is not the authorized H1 campaign")
    if campaign.get("campaign_id") != campaign_id:
        raise ValueError("campaign identity does not match the H1 authorization")
    if campaign.get("formal_h1_outcome_execution_authorized") is not True:
        raise ValueError("formal H1 execution is not authorized")
    if analysis.get("campaign_sha256") != _sha(campaign_path):
        raise ValueError("analysis does not bind the supplied campaign")
    if analysis.get("execution_summary_sha256") != _sha(execution_summary_path):
        raise ValueError("analysis does not bind the supplied execution summary")
    if execution.get("campaign_id") != campaign_id:
        raise ValueError("execution summary campaign identity does not match")

    verdict = analysis.get("acceptance_verdict")
    if not isinstance(verdict, dict) or verdict.get("level") not in {
        "PROXY_CANDIDATE",
        "NOT_ACCEPTED",
        "DIAGNOSTIC_ONLY",
    }:
        raise ValueError("analysis has no permitted Level-A candidate verdict")

    output_dir.mkdir(parents=True, exist_ok=False)
    outcome_path = output_dir / "level-a-outcome.json"
    provenance_path = output_dir / "provenance.json"
    seal_path = output_dir / "seal.json"
    _write(outcome_path, analysis)
    _write(
        provenance_path,
        {
            "schema_version": "phase2a.h1_level_a_provenance.v1",
            "campaign_id": campaign_id,
            "analysis_git_sha": analysis_git_sha,
            "execution_code_commit": campaign.get("execution_code_commit"),
            "campaign_path": str(campaign_path),
            "campaign_sha256": _sha(campaign_path),
            "execution_summary_path": str(execution_summary_path),
            "execution_summary_sha256": _sha(execution_summary_path),
            "source_analysis_path": str(analysis_path),
            "source_analysis_sha256": _sha(analysis_path),
            "raw_artifacts_modified": False,
            "failed_runs_preserved": True,
            "challenger_runtime_policy_switch_authorized": False,
        },
    )
    _write(
        seal_path,
        {
            "schema_version": "phase2a.h1_level_a_seal.v1",
            "campaign_id": campaign_id,
            "evidence_tier": "LEVEL_A_PROXY_FIRST",
            "primary_metric": "planned_return_weighted_prefill_proxy",
            "candidate_outcome": verdict["level"],
            "formal_verdict_pending_m1_m4_review": True,
            "verdict_ceiling": "PROXY_CANDIDATE",
            "level_b_runtime_claim_authorized": False,
            "files": {
                outcome_path.name: _sha(outcome_path),
                provenance_path.name: _sha(provenance_path),
            },
        },
    )
    return seal_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--execution-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--analysis-git-sha", required=True)
    arguments = parser.parse_args(argv)
    path = seal_h1_level_a_result(
        analysis_path=arguments.analysis,
        campaign_path=arguments.campaign,
        execution_summary_path=arguments.execution_summary,
        output_dir=arguments.output_dir,
        analysis_git_sha=arguments.analysis_git_sha,
    )
    print(f"wrote sealed H1 Level-A outcome bundle: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
