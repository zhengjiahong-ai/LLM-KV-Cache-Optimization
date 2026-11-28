from __future__ import annotations

import pytest

from kvopt.workload.phase5_official_continuum import (
    OBSERVATION_ONLY_CAPABILITIES,
    OFFICIAL_README_SHA256,
    OFFICIAL_REPOSITORY,
    OFFICIAL_REVISION,
    OfficialContinuumError,
    audit_official_continuum,
)


def _markers() -> dict[str, bool]:
    return {
        "scheduler_constructs_continuum_queue": True,
        "continuum_recorder_initialized": True,
        "tool_call_estimator_initialized": True,
    }


def _capabilities(value: str = "PASS") -> dict[str, str]:
    return {name: value for name in OBSERVATION_ONLY_CAPABILITIES}


def _audit(capabilities: dict[str, str]):
    return audit_official_continuum(
        repository=OFFICIAL_REPOSITORY,
        revision=OFFICIAL_REVISION,
        readme_sha256=OFFICIAL_README_SHA256,
        scheduler_policy_values=("fcfs", "priority", "continuum"),
        observed_source_markers=_markers(),
        integration_capabilities=capabilities,
    )


def test_official_observation_only_integration_passes() -> None:
    result = _audit(_capabilities())
    assert result["status"] == "PASS"
    assert result["execution_ready"] is True
    assert result["algorithm_modified"] is False


def test_missing_evidence_export_fails_closed() -> None:
    capabilities = _capabilities()
    capabilities["ENGINE_CORE_EVIDENCE_EXPORT"] = "NOT_IMPLEMENTED"
    result = _audit(capabilities)
    assert result["status"] == "FAIL_CLOSED_OBSERVATION_INCOMPLETE"
    assert result["missing_capabilities"] == ["ENGINE_CORE_EVIDENCE_EXPORT"]


def test_project_policy_in_official_arm_is_rejected() -> None:
    capabilities = _capabilities()
    capabilities["A3_SUFFIX"] = "PASS"
    with pytest.raises(OfficialContinuumError, match="project policy"):
        _audit(capabilities)


def test_wrong_upstream_revision_is_rejected() -> None:
    with pytest.raises(OfficialContinuumError, match="identity"):
        audit_official_continuum(
            repository=OFFICIAL_REPOSITORY,
            revision="0" * 40,
            readme_sha256=OFFICIAL_README_SHA256,
            scheduler_policy_values=("continuum",),
            observed_source_markers=_markers(),
            integration_capabilities=_capabilities(),
        )
