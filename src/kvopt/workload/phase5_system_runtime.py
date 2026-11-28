"""Frozen system-to-policy identities for Phase 5 Native execution."""

from __future__ import annotations

from collections.abc import Mapping

SYSTEM_RUNTIME_CONTRACTS: Mapping[str, Mapping[str, object]] = {
    "NATIVE": {
        "policy_id": "VLLM_NATIVE_LRU",
        "foundation": "PINNED_VLLM_0_27_1",
        "entry_release": "NONE",
        "scheduler": "NATIVE",
    },
    "CONTINUUM_OFFICIAL": {
        "policy_id": "CONTINUUM_OFFICIAL_316A5879",
        "foundation": "PINNED_PUBLIC_REPOSITORY",
        "entry_release": "OFFICIAL_RELEASED_BEHAVIOR",
        "scheduler": "OFFICIAL_CONTINUUM",
    },
    "CONTINUUM_ADAPTED": {
        "policy_id": "PROJECT_A0_FROZEN",
        "foundation": "PROJECT_CONTINUUM_ADAPTED",
        "entry_release": "A0_FROZEN",
        "scheduler": "PROJECT_PROGRAM_AWARE",
    },
    "A1_ORIGINAL": {
        "policy_id": "A1_ENTRY_COST_AWARE",
        "foundation": "PROJECT_CONTINUUM_ADAPTED",
        "entry_release": "A1_ORIGINAL",
        "scheduler": "PROJECT_PROGRAM_AWARE",
    },
    "A3_SUFFIX": {
        "policy_id": "A3_SUFFIX_COST_V1",
        "foundation": "PROJECT_CONTINUUM_ADAPTED",
        "entry_release": "A3_SUFFIX",
        "scheduler": "PROJECT_PROGRAM_AWARE",
    },
    "DVA_ER_V1": {
        "policy_id": "DVA_ER_V1_H60",
        "foundation": "PROJECT_CONTINUUM_ADAPTED",
        "entry_release": "DVA_ER_V1",
        "scheduler": "PROJECT_PROGRAM_AWARE",
    },
}


class SystemRuntimeContractError(ValueError):
    """A Native runtime attempted to install the wrong frozen policy."""


def validate_system_runtime_identity(
    *, system_id: str, policy_id: str, native_execution_architecture: str
) -> Mapping[str, object]:
    """Return the frozen runtime row or fail before EngineCore installation."""

    expected = SYSTEM_RUNTIME_CONTRACTS.get(system_id)
    if expected is None:
        raise SystemRuntimeContractError("unknown Phase 5 system identity")
    if policy_id != expected["policy_id"]:
        raise SystemRuntimeContractError(
            f"{system_id} policy identity differs from the frozen contract"
        )
    if native_execution_architecture != "ENGINE_CORE_PLUGIN_UTILITY_RPC_V1":
        raise SystemRuntimeContractError(
            f"{system_id} does not use the frozen EngineCore architecture"
        )
    return expected


def validate_no_policy_fallback(
    *, requested_system_id: str, installed_system_id: str, installed_policy_id: str
) -> None:
    """Prohibit a missing arm from silently running another system's policy."""

    if requested_system_id != installed_system_id:
        raise SystemRuntimeContractError("system identity fallback is prohibited")
    expected = SYSTEM_RUNTIME_CONTRACTS.get(requested_system_id)
    if expected is None or installed_policy_id != expected["policy_id"]:
        raise SystemRuntimeContractError("policy fallback is prohibited")
