from __future__ import annotations

from copy import deepcopy

import pytest

from kvopt.workload.phase5_swe_cohort import (
    EXPECTED_GROUPS,
    SWECohortError,
    materialize_swe_cohort,
    validate_swe_cohort,
)


def _inventory():
    rows = []
    for index, program_id in enumerate(x for group in EXPECTED_GROUPS for x in group):
        rows.append(
            {
                "program_id": program_id,
                "session_id": f"session-{index}",
                "trace_id": f"trace-{index}",
                "terminal_class": "NATURAL_TERMINAL" if index < 2 else "RIGHT_CENSORED",
                "censor_reason": None if index < 2 else "SOURCE_SESSION_RIGHT_CENSORED",
                "qualification_sha256": f"q-{index}",
                "raw_artifact_sha256": f"raw-{index}",
                "source_trace_sha256": f"source-{index}",
                "token_materialization_file_sha256": f"token-{index}",
            }
        )
    return {
        "existing_qualified_programs": rows[:35],
        "fresh_qualified_programs": rows[35:],
    }


def test_materializes_frozen_groups_arrivals_and_boundaries() -> None:
    outputs = materialize_swe_cohort(
        inventory=_inventory(), lineage_bindings={"inventory": "a" * 64}
    )
    validate_swe_cohort(outputs)
    groups = outputs["swe-group-manifest.json"]["groups"]
    assert len(groups) == 12
    assert all(len(group["repository_counts"]) >= 3 for group in groups)
    assert all(max(group["repository_counts"].values()) <= 2 for group in groups)
    arrivals = outputs["swe-frozen-poisson-arrival-manifest.json"]
    assert all(group["starts"][0]["start_offset_seconds"] == 0 for group in arrivals["groups"])
    assert arrivals["reuse_contract"]["per_system_resampling_allowed"] is False
    assert outputs["swe-workload-seal-input-bundle.json"]["workload_seal_issued"] is False


def test_rejects_inventory_membership_drift() -> None:
    inventory = _inventory()
    inventory["fresh_qualified_programs"][0]["program_id"] = "other__task-1"
    with pytest.raises(SWECohortError, match="frozen membership"):
        materialize_swe_cohort(inventory=inventory, lineage_bindings={})


def test_rejects_gpu_authorization_drift() -> None:
    outputs = materialize_swe_cohort(inventory=_inventory(), lineage_bindings={})
    changed = deepcopy(outputs)
    changed["swe-group-manifest.json"]["gpu_execution_authorized"] = True
    with pytest.raises(SWECohortError):
        validate_swe_cohort(changed)
