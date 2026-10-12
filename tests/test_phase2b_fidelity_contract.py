import json
from pathlib import Path

import pytest

from kvopt.workload.phase2 import Phase2Trace, PlannedRequest, PressureStage
from kvopt.workload.phase2b_fidelity import (
    CAPABILITY_NATIVE_APC_HASHES,
    CAPABILITY_TRUE_OVERLAP,
    FIDELITY_RUN_KIND,
    FidelityGateResult,
    FidelityPreflightError,
    load_fidelity_contract,
    validate_phase2b_preflight,
)


def _request(program: str, request: str, arrival: float = 0.0) -> PlannedRequest:
    return PlannedRequest(
        program_id=program,
        request_id=request,
        turn_index=1,
        planned_arrival_offset_seconds=arrival,
        prompt="prompt",
        prefix_prompt="prefix",
        is_terminal=True,
        next_tool_type=None,
        tool_gap_seconds=None,
    )


def _contract(tmp_path: Path, capabilities: list[str]) -> object:
    path = tmp_path / "contract.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "phase2b.fidelity_contract.v1",
                "run_kind": FIDELITY_RUN_KIND,
                "case_id": "AR-S1",
                "required_capabilities": capabilities,
                "constraints": {"max_in_flight": 2, "timeout_seconds": 120},
            }
        ),
        encoding="utf-8",
    )
    return load_fidelity_contract(path)


def _config() -> dict[str, object]:
    return {
        "backend_options": {
            "phase2b_fidelity_mode": True,
            "prefix_generator_version": "phase2b-prefix-v1",
            "prefix_content_key_by_program": {
                "agent-a": "shared-0",
                "agent-b": "shared-0",
            },
            "program_prefix_tokens": {"agent-a": 256, "agent-b": 256},
            "executor_mode": "submit_collect",
        },
        "batching": {"max_concurrent_requests": 2},
        "cache": {"block_size": 16},
    }


def _trace() -> Phase2Trace:
    return Phase2Trace(
        "phase2b-fixture",
        (_request("agent-a", "a:1"), _request("agent-b", "b:1")),
        (),
    )


def test_preflight_accepts_explicit_opt_in_shared_overlap(tmp_path: Path) -> None:
    contract = _contract(
        tmp_path,
        [CAPABILITY_TRUE_OVERLAP, CAPABILITY_NATIVE_APC_HASHES],
    )

    validate_phase2b_preflight(
        contract=contract,
        config=_config(),
        trace=_trace(),
        supported_capabilities=(
            CAPABILITY_TRUE_OVERLAP,
            CAPABILITY_NATIVE_APC_HASHES,
        ),
        platform_ready=True,
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda config: config["backend_options"].pop("prefix_content_key_by_program"), "content"),
        (lambda config: config["backend_options"].update({"executor_mode": "legacy_sync"}), "submit_collect"),
        (lambda config: config["batching"].update({"max_concurrent_requests": 1}), "contract cap"),
        (lambda config: config["backend_options"]["program_prefix_tokens"].update({"agent-a": 24}), "align"),
    ),
)
def test_preflight_fails_closed(tmp_path: Path, mutation, message: str) -> None:
    contract = _contract(tmp_path, [CAPABILITY_TRUE_OVERLAP])
    config = _config()
    mutation(config)

    with pytest.raises(FidelityPreflightError, match=message):
        validate_phase2b_preflight(
            contract=contract,
            config=config,
            trace=_trace(),
            supported_capabilities=(CAPABILITY_TRUE_OVERLAP,),
            platform_ready=True,
        )


def test_preflight_requires_warmup_before_native_pressure(tmp_path: Path) -> None:
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(
        json.dumps(
            {
                "schema_version": "phase2b.fidelity_contract.v1",
                "run_kind": FIDELITY_RUN_KIND,
                "case_id": "PR-S1",
                "required_capabilities": ["native_hashed_eviction"],
                "constraints": {"max_in_flight": 1, "timeout_seconds": 120},
            }
        ),
        encoding="utf-8",
    )
    contract = load_fidelity_contract(contract_path)
    config = _config()
    config["backend_options"]["prefix_content_key_by_program"] = {}
    config["backend_options"]["program_prefix_tokens"] = {}
    config["batching"]["max_concurrent_requests"] = 1
    trace = Phase2Trace(
        "pressure-without-warmup",
        (),
        (PressureStage("p", 0.0, "pressure", 1, True),),
    )

    with pytest.raises(FidelityPreflightError, match="target warmup"):
        validate_phase2b_preflight(
            contract=contract,
            config=config,
            trace=trace,
            supported_capabilities=("native_hashed_eviction",),
            platform_ready=True,
        )


def test_gate_result_requires_auditable_status_and_reason() -> None:
    result = FidelityGateResult(
        gate="G-INFLIGHT",
        requested={"peak_inflight": 2},
        observed={"peak_inflight": 1},
        status="NOT_DEMONSTRATED",
        source_event_indices=(4, 9),
        scope="request_lifecycle",
        runtime_identity={"backend": "fake"},
        reason="planned overlap did not become native overlap",
        clock_domain="system_monotonic",
    )

    assert result.to_dict()["status"] == "NOT_DEMONSTRATED"
