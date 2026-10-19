from pathlib import Path

import pytest

from kvopt.workload.phase2g_a2_profile_decision_impact import audit_decision_impact

REPOSITORY = Path(__file__).parents[1]


def test_frozen_campaign_profile_repair_does_not_change_policy_input() -> None:
    manifest = (
        REPOSITORY
        / "artifacts/phase2g-a2-native-gate2-campaign-v3/manifest.json"
    )
    smoke = REPOSITORY / "artifacts/phase2g-a2-profile-repair-smoke-runs-v1"
    if not manifest.is_file() or not smoke.is_dir():
        pytest.skip("generated profile-repair evidence is not present")
    report = audit_decision_impact(
        manifest_path=manifest,
        legacy_profile=(
            REPOSITORY
            / "docs/experiments/phase1b-continuum/artifacts/"
            "prefill-reload-profile-formal-20260920T045859Z-6183d106.json"
        ),
        extended_profile=(
            REPOSITORY
            / "docs/experiments/phase2g-a2-profile-repair/"
            "prefill-reload-profile-extended-544.json"
        ),
        smoke_root=smoke,
    )

    assert report["decision_impact"] == "NO_POLICY_INPUT_CHANGE_UNDER_COLD_START"
    assert report["representative_point_exactly_preserved"] is True
    assert report["maximum_requests_in_any_scenario"] <= 100
    assert report["native_smoke_maximum_observed_history_sample_count"] <= 100
