from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_bfcl_extract_preflight import (
    BFCLExtractPreflightError,
    evaluate_extract_preflight,
)

CONFIG = Path("configs/phase5/phase5-bfcl-extract-pilot-preflight-v1.json")


def _review() -> dict[str, object]:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_unclear_publisher_and_access_conditions_fail_before_call() -> None:
    report = evaluate_extract_preflight(_review())
    assert report["status"] == "FAIL_CLOSED_PRE_CALL"
    assert report["total_extract_call_count"] == 0
    assert all(
        row["failure_code"] == "THIRD_PARTY_CONTENT_ACCESS_NOT_AUTHORIZED"
        for row in report["url_results"]
    )
    assert all(row["extract_call_status"] == "NOT_CALLED" for row in report["url_results"])


def test_preflight_rejects_url_substitution() -> None:
    review = copy.deepcopy(_review())
    review["urls"][0]["url"] = "https://example.test/substitute"
    with pytest.raises(BFCLExtractPreflightError, match="scope differs"):
        evaluate_extract_preflight(review)


def test_all_conditions_must_be_true_before_single_call_readiness() -> None:
    review = _review()
    review["publisher"]["express_permission_observed"] = True
    for row in review["urls"]:
        row["publisher_permission_clear"] = True
        row["robots_observable"] = True
        row["page_access_observable"] = True
        row["paywall_absence_proven"] = True
    report = evaluate_extract_preflight(review)
    assert report["status"] == "READY_FOR_SINGLE_CALLS"
    assert report["total_extract_call_count"] == 0
