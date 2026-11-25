from __future__ import annotations

import pytest

from kvopt.profiling.phase5_downstream_observation import join_downstream_observations


def _physical():
    return {
        "status": "PASS",
        "decision_id": "d1",
        "block_content_identities": {"10": "content-a", "11": "HASHLESS"},
    }


def test_downstream_revisit_reports_nec_without_causal_claim() -> None:
    report = join_downstream_observations(
        physical_evidence=_physical(),
        observations=[
            {
                "request_id": "r2",
                "program_id": "p2",
                "session_id": "s2",
                "prefix_content_identities": ["content-a"],
                "native_prompt_tokens": 100,
                "reusable_prefix_tokens": 80,
                "native_cached_tokens": 48,
            }
        ],
    )
    row = report["observations"][0]
    assert row["revisited_victim_content_identities"] == ["content-a"]
    assert row["observed_recomputed_tokens"] == 32
    assert row["eviction_causal_attribution"] == "NOT_ESTABLISHED"


def test_downstream_missing_identity_and_invalid_nec_fail_closed() -> None:
    with pytest.raises(ValueError, match="identity"):
        join_downstream_observations(
            physical_evidence=_physical(),
            observations=[{"request_id": "r2", "prefix_content_identities": None}],
        )
    with pytest.raises(ValueError, match="invariant"):
        join_downstream_observations(
            physical_evidence=_physical(),
            observations=[
                {
                    "request_id": "r2",
                    "prefix_content_identities": [],
                    "native_prompt_tokens": 10,
                    "reusable_prefix_tokens": 5,
                    "native_cached_tokens": 6,
                }
            ],
        )
