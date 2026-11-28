"""Compatibility contract for the frozen Continuum Official Calibration arm."""

from __future__ import annotations

from collections.abc import Mapping

from .phase5_replay import canonical_sha256

OFFICIAL_REPOSITORY = "https://github.com/Hanchenli/vllm-continuum"
OFFICIAL_REVISION = "316a58794a6ff86b216e579b74fd56ed0c5a911f"
OFFICIAL_README_SHA256 = (
    "580711553689db98f6a5a2bfa9ee97cb3ab98b87c1fef4fd5f0c159e2f90fbe6"
)
OBSERVATION_ONLY_CAPABILITIES = (
    "PROGRAM_SESSION_REQUEST_IDENTITY",
    "NATIVE_PREFIX_BLOCK_OBSERVATION",
    "N_E_C_METRICS",
    "ENGINE_CORE_EVIDENCE_EXPORT",
    "RUN_MANIFEST_AND_ARCHIVE",
)
PROHIBITED_PROJECT_POLICIES = (
    "CONTINUUM_ADAPTED",
    "A1_ORIGINAL",
    "A3_SUFFIX",
    "DVA_ER_V1",
)


class OfficialContinuumError(ValueError):
    """The Official arm identity or observation-only boundary drifted."""


def audit_official_continuum(
    *,
    repository: str,
    revision: str,
    readme_sha256: str,
    scheduler_policy_values: tuple[str, ...],
    observed_source_markers: Mapping[str, bool],
    integration_capabilities: Mapping[str, str],
) -> dict[str, object]:
    """Audit the upstream identity and the minimal non-policy integration.

    A missing observation capability makes the arm not execution-ready.  Any
    project-side policy marker is a harder contract violation because it would
    stop being the frozen Official comparison system.
    """

    if repository != OFFICIAL_REPOSITORY or revision != OFFICIAL_REVISION:
        raise OfficialContinuumError("Official repository identity drifted")
    if readme_sha256 != OFFICIAL_README_SHA256:
        raise OfficialContinuumError("Official README identity drifted")
    if "continuum" not in scheduler_policy_values:
        raise OfficialContinuumError("Official scheduler lacks continuum policy")
    required_markers = {
        "scheduler_constructs_continuum_queue",
        "continuum_recorder_initialized",
        "tool_call_estimator_initialized",
    }
    if set(observed_source_markers) != required_markers or not all(
        observed_source_markers.values()
    ):
        raise OfficialContinuumError("Official scheduler source markers are incomplete")
    prohibited = sorted(
        policy
        for policy in PROHIBITED_PROJECT_POLICIES
        if integration_capabilities.get(policy) not in (None, "ABSENT")
    )
    if prohibited:
        raise OfficialContinuumError(
            "Official integration contains project policy: " + ",".join(prohibited)
        )
    missing = sorted(
        capability
        for capability in OBSERVATION_ONLY_CAPABILITIES
        if integration_capabilities.get(capability) != "PASS"
    )
    payload = {
        "schema_version": "phase5.continuum_official_compatibility.v1",
        "system_id": "CONTINUUM_OFFICIAL",
        "repository": repository,
        "revision": revision,
        "readme_sha256": readme_sha256,
        "scheduler_policy": "continuum",
        "paper_exact": False,
        "environment": "OFFICIAL_DOCUMENTED_ENVIRONMENT",
        "environment_confound": True,
        "source_markers": dict(observed_source_markers),
        "observation_only_capabilities": dict(integration_capabilities),
        "prohibited_project_policies": list(PROHIBITED_PROJECT_POLICIES),
        "missing_capabilities": missing,
        "algorithm_modified": False,
        "execution_ready": not missing,
        "status": "PASS" if not missing else "FAIL_CLOSED_OBSERVATION_INCOMPLETE",
    }
    return {**payload, "audit_sha256": canonical_sha256(payload)}
