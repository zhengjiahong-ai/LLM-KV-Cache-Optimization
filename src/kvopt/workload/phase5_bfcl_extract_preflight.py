"""Fail-closed pre-call review for the bounded BFCL Tavily Extract pilot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .phase5_replay import canonical_sha256

EXPECTED_URLS = {
    "web_search_base_0": (
        "https://www.forbes.com/2025/04/17/"
        "billionaires-from-the-worlds-most-expensive-tea/"
    ),
    "web_search_no_snippet_0": (
        "https://www.forbes.com/2025/04/07/"
        "billionaires-from-the-worlds-most-expensive-tea/"
    ),
}


class BFCLExtractPreflightError(ValueError):
    """Raised when the bounded URL review input violates the frozen scope."""


def evaluate_extract_preflight(review: Mapping[str, Any]) -> dict[str, object]:
    """Evaluate whether either authorized URL may receive its sole API call."""

    rows = review.get("urls")
    if not isinstance(rows, list) or len(rows) != 2:
        raise BFCLExtractPreflightError("exactly two URL review rows are required")
    observed = {str(row.get("case_id")): str(row.get("url")) for row in rows}
    if observed != EXPECTED_URLS:
        raise BFCLExtractPreflightError("URL scope differs from M1 authorization")

    provider = review.get("provider")
    publisher = review.get("publisher")
    if not isinstance(provider, Mapping) or not isinstance(publisher, Mapping):
        raise BFCLExtractPreflightError("provider and publisher reviews are required")

    url_results = []
    for row in rows:
        checks = {
            "TAVILY_RETENTION_ALLOWED": bool(
                provider.get("storage_and_internal_replay_allowed")
            ),
            "PUBLISHER_PERMISSION_CLEAR": bool(
                row.get("publisher_permission_clear")
            )
            and bool(publisher.get("express_permission_observed")),
            "ROBOTS_OBSERVABLE": bool(row.get("robots_observable")),
            "PAGE_ACCESS_OBSERVABLE": bool(row.get("page_access_observable")),
            "PAYWALL_ABSENCE_PROVEN": bool(row.get("paywall_absence_proven")),
        }
        blockers = [name for name, passed in checks.items() if not passed]
        allowed = not blockers
        url_results.append(
            {
                "case_id": row["case_id"],
                "url": row["url"],
                "robots_source": row.get("robots_source"),
                "robots_observation": row.get("robots_observation"),
                "page_access_observation": row.get("page_access_observation"),
                "checks": checks,
                "status": "READY_FOR_SINGLE_CALL" if allowed else "FAIL_CLOSED",
                "extract_call_status": "NOT_CALLED",
                "extract_call_count": 0,
                "fixture_status": "NOT_CREATED",
                "response_sha256": None,
                "failure_code": (
                    None
                    if allowed
                    else "THIRD_PARTY_CONTENT_ACCESS_NOT_AUTHORIZED"
                ),
                "blockers": blockers,
                "url_substitution": False,
                "query_substitution": False,
                "snippet_used_as_page_content": False,
            }
        )

    ready = all(row["status"] == "READY_FOR_SINGLE_CALL" for row in url_results)
    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_extract_preflight.v1",
        "status": "READY_FOR_SINGLE_CALLS" if ready else "FAIL_CLOSED_PRE_CALL",
        "review_date": review.get("review_date"),
        "scope": review.get("scope"),
        "url_results": url_results,
        "total_extract_call_count": 0,
        "original_pilot_preserved": True,
        "private_body_evidence_created": False,
        "credentials_recorded": False,
        "formal_cohort_selected": False,
        "bfcl_200_case_authorized": False,
        "gpu_execution_authorized": False,
    }
    return {**payload, "preflight_sha256": canonical_sha256(payload)}
