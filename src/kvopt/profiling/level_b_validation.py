"""Evaluate S1-S5 Level-B seam-validation artifacts."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from .ingestion import load_run_artifacts
from .runtime_evidence import (
    RequestRuntimeEvidenceRow,
    build_request_runtime_evidence_table,
)


@dataclass(frozen=True, slots=True)
class SeamValidationResult:
    case_id: str
    request_id: str
    expected_semantics: str
    outcome: str
    reason: str | None
    native_prompt_tokens: int | None
    eligible_prefix_tokens: int | None
    native_cached_prefix_tokens: int | None
    actual_prefill_tokens: int | None
    observed_recomputed_tokens: int | None
    apc_outcome: str | None
    native_clock_domain: str | None
    native_queued_timestamp: float | None
    native_scheduler_admission_timestamp: float | None
    native_first_token_timestamp: float | None
    native_queue_delay_status: str
    native_prefill_to_first_token_status: str
    capability_statuses: dict[str, str]


def _case_assertion(
    case_id: str,
    row: RequestRuntimeEvidenceRow,
) -> tuple[bool, str | None]:
    if row.availability != "AVAILABLE":
        return False, row.unavailable_reason or "token_evidence_unavailable"
    n = row.native_prompt_tokens
    e = row.eligible_prefix_tokens
    c = row.native_cached_prefix_tokens
    w = row.actual_prefill_tokens
    r = row.observed_recomputed_tokens
    if None in {n, e, c, w, r}:
        return False, "derived_token_field_missing"
    assert n is not None and e is not None and c is not None
    assert w is not None and r is not None
    if case_id.startswith("s1-"):
        passed = e == 0 and r == 0 and row.apc_outcome == "NO_REUSE_ELIGIBLE_PREFIX"
        return passed, None if passed else "expected cold no-eligible-prefix semantics"
    if case_id.startswith("s2-"):
        passed = e > 0 and c == e and r == 0 and row.apc_outcome == "FULL_HIT"
        return passed, None if passed else "expected a native full reusable hit"
    if case_id.startswith("s3-"):
        passed = 0 < c < e and r == e - c and row.apc_outcome == "PARTIAL_HIT"
        return passed, None if passed else "expected a controlled partial-prefix hit"
    if case_id.startswith("s4-"):
        passed = e > 0 and c == 0 and r == e and row.apc_outcome == "MISS"
        return passed, None if passed else "expected full loss of a reusable prefix"
    if case_id.startswith("s5-"):
        passed = e > 0 and n > e and w == r + (n - e)
        return passed, None if passed else "fresh suffix was not separated from recompute"
    return False, "unknown seam-validation case"


def _capability_statuses(manifest: dict[str, object]) -> dict[str, str]:
    raw = manifest.get("observation_availability")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, str] = {}
    for name, value in raw.items():
        if isinstance(name, str) and isinstance(value, dict):
            status = value.get("status")
            if isinstance(status, str):
                result[name] = status
    return result


def build_seam_validation_report(
    campaign_path: str | Path,
    run_root: str | Path,
) -> dict[str, object]:
    campaign_file = Path(campaign_path)
    campaign = json.loads(campaign_file.read_text(encoding="utf-8"))
    if not isinstance(campaign, dict) or campaign.get("schema_version") != (
        "phase2a.level_b_seam_validation.v1"
    ):
        raise ValueError("unsupported seam-validation campaign")
    if campaign.get("formal_h1_evidence") is not False:
        raise ValueError("seam-validation campaign must not be formal H1 evidence")
    scenarios = campaign.get("scenarios")
    if not isinstance(scenarios, list):
        raise TypeError("campaign scenarios must be an array")

    results: list[SeamValidationResult] = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise TypeError("campaign scenario must be an object")
        case_id = scenario.get("case_id")
        request_id = scenario.get("target_request_id")
        expected = scenario.get("expected_semantics")
        if not all(isinstance(value, str) for value in (case_id, request_id, expected)):
            raise TypeError("scenario identity fields must be text")
        assert isinstance(case_id, str)
        assert isinstance(request_id, str)
        assert isinstance(expected, str)
        artifacts = load_run_artifacts(Path(run_root) / case_id)
        rows = build_request_runtime_evidence_table((artifacts,))
        matches = [row for row in rows if row.request_id == request_id]
        if len(matches) != 1:
            raise ValueError(f"{case_id} target request must have exactly one row")
        row = matches[0]
        passed, reason = _case_assertion(case_id, row)
        results.append(
            SeamValidationResult(
                case_id=case_id,
                request_id=request_id,
                expected_semantics=expected,
                outcome=(
                    "UNAVAILABLE"
                    if row.availability != "AVAILABLE"
                    else "PASS" if passed else "FAIL"
                ),
                reason=reason,
                native_prompt_tokens=row.native_prompt_tokens,
                eligible_prefix_tokens=row.eligible_prefix_tokens,
                native_cached_prefix_tokens=row.native_cached_prefix_tokens,
                actual_prefill_tokens=row.actual_prefill_tokens,
                observed_recomputed_tokens=row.observed_recomputed_tokens,
                apc_outcome=row.apc_outcome,
                native_clock_domain=row.native_clock_domain,
                native_queued_timestamp=row.native_queued_timestamp,
                native_scheduler_admission_timestamp=(
                    row.native_scheduler_admission_timestamp
                ),
                native_first_token_timestamp=row.native_first_token_timestamp,
                native_queue_delay_status=row.native_queue_delay_status,
                native_prefill_to_first_token_status=(
                    row.native_prefill_to_first_token_status
                ),
                capability_statuses=_capability_statuses(artifacts.manifest),
            )
        )
    overall = "PASS" if all(row.outcome == "PASS" for row in results) else "BLOCKED"
    return {
        "schema_version": "phase2a.level_b_seam_validation_report.v1",
        "campaign_id": campaign.get("campaign_id"),
        "formal_h1_evidence": False,
        "overall_outcome": overall,
        "case_results": [asdict(row) for row in results],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    report = build_seam_validation_report(arguments.campaign, arguments.run_root)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{report['overall_outcome']}: {arguments.output.resolve()}")
    return 0 if report["overall_outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
