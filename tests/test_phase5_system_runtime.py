from __future__ import annotations

import pytest

from kvopt.workload.phase5_calibration import SYSTEM_IDS
from kvopt.workload.phase5_system_runtime import (
    SYSTEM_RUNTIME_CONTRACTS,
    SystemRuntimeContractError,
    validate_no_policy_fallback,
    validate_system_runtime_identity,
)


def test_exact_six_system_runtime_contracts_are_frozen() -> None:
    assert set(SYSTEM_RUNTIME_CONTRACTS) == set(SYSTEM_IDS)
    for system_id in SYSTEM_IDS:
        expected = SYSTEM_RUNTIME_CONTRACTS[system_id]
        assert (
            validate_system_runtime_identity(
                system_id=system_id,
                policy_id=str(expected["policy_id"]),
                native_execution_architecture="ENGINE_CORE_PLUGIN_UTILITY_RPC_V1",
            )
            == expected
        )


def test_a3_cannot_stand_in_for_dva() -> None:
    with pytest.raises(SystemRuntimeContractError, match="policy identity"):
        validate_system_runtime_identity(
            system_id="DVA_ER_V1",
            policy_id="A3_SUFFIX_COST_V1",
            native_execution_architecture="ENGINE_CORE_PLUGIN_UTILITY_RPC_V1",
        )


def test_cross_system_fallback_is_rejected() -> None:
    with pytest.raises(SystemRuntimeContractError, match="fallback"):
        validate_no_policy_fallback(
            requested_system_id="A1_ORIGINAL",
            installed_system_id="A3_SUFFIX",
            installed_policy_id="A3_SUFFIX_COST_V1",
        )


def test_wrong_runtime_architecture_is_rejected() -> None:
    with pytest.raises(SystemRuntimeContractError, match="architecture"):
        validate_system_runtime_identity(
            system_id="NATIVE",
            policy_id="VLLM_NATIVE_LRU",
            native_execution_architecture="FRONTEND_SHADOW_STATE",
        )
