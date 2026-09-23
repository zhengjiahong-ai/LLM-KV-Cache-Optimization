from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kvopt.continuum import (
    BlockIdentity,
    BlocksObserved,
    FakeClock,
    FollowupWaiting,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestArrived,
    RequestIdentity,
    TurnFinished,
)
from kvopt.continuum.runtime import build_runtime
from kvopt.continuum.selection import PressureReleaseEffect, RetentionEntryKey
from scripts.spikes.run_continuum_phase1b_validation_metal import (
    DEFAULT_EXECUTION_FACTORY,
    PRESSURE_TOKEN_COUNT,
    REQUIRED_CLAIMS,
    TARGET_TOKEN_COUNT,
    RequestExecutionEvidence,
    ValidationExecutionAdapter,
    ValidationExecutionError,
    ValidationRun,
    _admit_ordinary_and_defer_followup,
    _build_observation_phase_gate,
    _capture_live_block_pool,
    _coherent_child_request_snapshot,
    _controlled_pressure_llm_kwargs,
    _controlled_request_roles,
    _deferred_followup_finish_timestamp,
    _EvictionEvidenceProxy,
    _normalize_child_completion_ids,
    _qualified_pressure_token_ids,
    _qualified_target_token_ids,
    _read_target_presence,
    _require_real_pressure_batch,
    _run_mode_child,
    run_adaptive_pressure,
)


def _run() -> ValidationRun:
    return ValidationRun(
        run_id="pr7-test",
        git_sha="a" * 40,
        provenance={"platform": "test"},
    )


def _record_valid_lifecycle(run: ValidationRun) -> None:
    run.record_request("program-a", "native-1")
    run.record_request("program-a", "native-2")
    run.record_lifecycle("program-a", "native-1", "REQUEST_ARRIVED")
    run.record_lifecycle("program-a", "native-1", "REQUEST_ADMITTED")
    run.record_lifecycle("program-a", "native-1", "BLOCKS_OBSERVED")
    run.record_actual_token_count("program-a", "native-1", 128)
    run.record_ttl_decision(
        "program-a",
        "native-1",
        token_count=128,
        prefill_reload_seconds=0.25,
    )
    run.record_lifecycle(
        "program-a", "native-1", "TURN_FINISHED_NON_TERMINAL"
    )


def _record_all_passing_claims(run: ValidationRun) -> None:
    for claim in REQUIRED_CLAIMS:
        run.record_claim(claim, True, evidence={"source": "test"})
    for mode in ("NATIVE", "SHADOW", "CONTROLLED"):
        run.record_mode_evidence(mode, observed=True)
    run.record_native_cleanup(7, evicted=True)
    run.record_scenario("controlled_multiturn", passed=True, evidence={})
    run.record_scenario("pressure_native_cleanup", passed=True, evidence={})


def test_program_and_request_identity_are_recorded_without_inference() -> None:
    run = _run()

    run.record_request("program-a", "native-1")
    run.record_request("program-a", "native-2")

    evidence = run.snapshot()

    assert evidence["requests"] == [
        {
            "program_id": "program-a",
            "request_id": "native-1",
            "native_request_id": None,
        },
        {
            "program_id": "program-a",
            "request_id": "native-2",
            "native_request_id": None,
        },
    ]


def test_invalid_lifecycle_cannot_produce_complete_artifact() -> None:
    run = _run()
    run.record_request("program-a", "request-1")

    with pytest.raises(ValueError):
        run.record_lifecycle("program-a", "request-1", "REQUEST_ADMITTED")

    run.record_claim("program_continuity", True)
    assert run.finalize()["status"] == "incomplete"


def test_actual_token_count_is_preserved_for_ttl_evidence() -> None:
    run = _run()
    _record_valid_lifecycle(run)

    evidence = run.snapshot()

    assert evidence["actual_token_counts"] == [
        {
            "program_id": "program-a",
                "request_id": "native-1",
            "token_count": 128,
        }
    ]
    assert evidence["ttl_decisions"][0]["token_count"] == 128
    assert evidence["ttl_decisions"][0]["token_count"] != 256


def test_prefix_observation_is_retained_in_auditable_artifact() -> None:
    run = _run()
    run.record_request("program-a", "request-1")

    run.record_prefix_observation(
        program_id="program-a",
        request_id="request-1",
        prefix_id="prefix-a",
        block_ids=(7, 8),
    )

    assert run.snapshot()["prefix_observations"] == [
        {
            "program_id": "program-a",
            "request_id": "request-1",
            "prefix_id": "prefix-a",
            "block_ids": [7, 8],
        }
    ]


def test_artifact_starts_incomplete_and_becomes_complete_only_after_all_claims(
    tmp_path: Path,
) -> None:
    run = _run()
    path = tmp_path / "validation.json"

    run.write_artifact(path)
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "incomplete"

    _record_all_passing_claims(run)
    run.finalize()
    run.write_artifact(path)

    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact["schema"] == "continuum.phase1b.validation.v1"
    assert artifact["status"] == "complete"


def test_failed_claim_keeps_artifact_incomplete_with_reason() -> None:
    run = _run()
    _record_all_passing_claims(run)
    run.record_claim(
        "native_cleanup",
        False,
        failure_reason="native eviction signal missing",
    )

    artifact = run.finalize()

    assert artifact["status"] == "incomplete"
    assert "native eviction signal missing" in artifact["failure_reason"]


def test_mode_evidence_is_recorded_separately() -> None:
    run = _run()

    run.record_mode_evidence("NATIVE", queue_mutated=False)
    run.record_mode_evidence("SHADOW", queue_mutated=False)
    run.record_mode_evidence("CONTROLLED", queue_mutated=True)

    assert run.snapshot()["mode_boundaries"] == {
        "NATIVE": {"queue_mutated": False},
        "SHADOW": {"queue_mutated": False},
        "CONTROLLED": {"queue_mutated": True},
    }


def test_native_cleanup_claim_requires_native_eviction_signal() -> None:
    run = _run()
    for claim in REQUIRED_CLAIMS:
        run.record_claim(claim, True)
    for mode in ("NATIVE", "SHADOW", "CONTROLLED"):
        run.record_mode_evidence(mode, observed=True)
    run.record_scenario("controlled_multiturn", passed=True, evidence={})
    run.record_scenario("pressure_native_cleanup", passed=True, evidence={})

    assert run.finalize()["status"] == "incomplete"

    run.record_native_cleanup(7, evicted=True)
    assert run.finalize()["status"] == "complete"


def test_adaptive_pressure_stops_on_evidence_and_fails_at_safety_ceiling() -> None:
    batches: list[int] = []

    result = run_adaptive_pressure(
        run_batch=lambda batch: batches.append(batch),
        observe=lambda: {"target_present": len(batches) < 17},
        evidence_ready=lambda observation: observation["target_present"] is False,
        safety_ceiling=64,
    )

    assert result.passed is True
    assert result.batches == 17
    assert result.pressure_requests == 17 * 32
    assert result.stop_reason == "evidence"

    batches.clear()
    result = run_adaptive_pressure(
        run_batch=lambda batch: batches.append(batch),
        observe=lambda: {"target_present": True},
        evidence_ready=lambda observation: observation["target_present"] is False,
        safety_ceiling=2,
    )

    assert result.passed is False
    assert result.batches == 2
    assert result.stop_reason == "safety_ceiling"


class _Provider:
    def estimate(self, token_count: int):
        assert token_count == 128
        return 0.25, InputProvenance(InputSource.APPROXIMATED, "test profile")


def _runtime_for_adapter() -> tuple[object, FakeClock]:
    clock = FakeClock(5.0)
    runtime = build_runtime(
        clock=clock,
        prefill_reload_provider=_Provider(),
        default_ttl_seconds=7.0,
    )
    return runtime, clock


def _request_executor(
    program_id: str, request_id: str, terminal: bool
) -> RequestExecutionEvidence:
    index_by_request = {
        "request-1": 1,
        "request-followup": 99,
        "request-ordinary": 98,
        "request-3": 3,
        "request-4": 4,
    }
    index = index_by_request.get(request_id)
    if index is None:
        index = int(request_id.removeprefix("request-"))
    timestamp_by_request = {
        "request-1": 4.1,
        "request-followup": 4.4,
        "request-ordinary": 4.5,
        "request-3": 4.8,
        "request-4": 4.8,
    }
    timestamp = timestamp_by_request.get(request_id, float(index))
    native_request_id = f"native-request-{index}"
    return RequestExecutionEvidence(
        program_id=program_id,
        request_id=native_request_id,
        native_request_id=native_request_id,
        external_request_id=request_id,
        token_count=128,
        prefix_id=f"prefix-{index}",
        block_ids=(index,),
        arrival_timestamp=timestamp,
        admission_timestamp=timestamp + 0.05,
        finish_timestamp=timestamp + 0.1,
        terminal=terminal,
        next_tool_type=None if terminal else "search",
    )


def _mode_evidence(mode: str) -> dict[str, object]:
    if mode == "NATIVE":
        return {
            "mode": mode,
            "queue_mutated": False,
            "continuum_invoked": False,
            "real_runtime_observed": True,
            "native_path_succeeded": True,
            "hook_installed": False,
            "hook_exercised": False,
        }
    if mode == "SHADOW":
        return {
            "mode": mode,
            "hypothetical_plan_available": True,
            "queue_mutated": False,
            "hook_installed": True,
            "hook_exercised": True,
            "continuum_invoked": True,
            "real_runtime_observed": True,
        }
    return {
        "mode": mode,
        "queue_mutated": True,
        "hook_installed": True,
        "hook_exercised": True,
        "continuum_invoked": True,
        "real_runtime_observed": True,
        "hypothetical_plan_available": False,
        "ordering_outcome": "followup_before_ordinary",
        "completion_ordering": "followup_before_ordinary",
    }


def _successful_adapter(
    run: ValidationRun,
    *,
    pressure_batch_executor=None,
    pressure_observer=None,
    mode_executor=_mode_evidence,
    scheduler_executor=None,
) -> ValidationExecutionAdapter:
    runtime, clock = _runtime_for_adapter()
    if pressure_batch_executor is None:
        pressure_batch_executor = lambda batch: {
            "completed_native_request_ids": tuple(
                f"pressure-{batch}-{index}" for index in range(32)
            )
        }
    if pressure_observer is None:
        pressure_observer = lambda: {
            "target_present": False,
            "retention_release_observed": True,
            "plan_validated": True,
            "native_eviction_callback_observed": True,
            "hashes_cleared": True,
            "evicted_block_id": 7,
        }
    if scheduler_executor is None:
        scheduler_executor = lambda _runtime, _request_ids: {
            "hook_boundary": "vllm.scheduler.schedule",
            "waiting_request_ids": ("native-request-98", "native-request-99"),
            "ordered_request_ids": ("native-request-99", "native-request-98"),
            "hook_installed": True,
            "hook_exercised": True,
            "real_runtime_observed": True,
            "completed_native_request_ids": ("native-request-99", "native-request-98"),
            "completed_external_request_ids": ("request-followup", "request-ordinary"),
            "followup_request_id": "native-request-99",
            "ordinary_request_id": "native-request-98",
            "completion_ordering": "followup_before_ordinary",
        }
    return ValidationExecutionAdapter(
        run=run,
        runtime=runtime,
        clock=clock,
        request_executor=_request_executor,
        pressure_batch_executor=pressure_batch_executor,
        pressure_observer=pressure_observer,
        mode_executor=mode_executor,
        scheduler_executor=scheduler_executor,
        ordinary_request_executor=lambda program_id, external_id: _request_executor(
            program_id, external_id, False
        ),
    )


def test_execution_adapter_derives_program_continuity_from_distinct_requests() -> None:
    run = _run()
    adapter = _successful_adapter(run)

    assert adapter.run_controlled_multiturn() is True
    claim = run.snapshot()["claims"]["program_continuity"]

    assert claim["status"] == "PASS"
    assert claim["evidence"]["distinct_request_ids"] == [
        "native-request-1",
        "native-request-3",
    ]


def test_nonterminal_retention_requires_observed_live_state() -> None:
    run = _run()
    runtime, clock = _runtime_for_adapter()
    adapter = ValidationExecutionAdapter(
        run=run,
        runtime=runtime,
        clock=clock,
        request_executor=_request_executor,
        pressure_batch_executor=lambda _batch: {
            "completed_native_request_ids": tuple(
                f"pressure-{_batch}-{index}" for index in range(32)
            )
        },
        pressure_observer=lambda: {"target_present": False},
        mode_executor=_mode_evidence,
        scheduler_executor=lambda _runtime, _request_ids: {
            "hook_boundary": "vllm.scheduler.schedule",
            "waiting_request_ids": ("native-request-98", "native-request-99"),
            "ordered_request_ids": ("native-request-99", "native-request-98"),
            "hook_installed": True,
            "hook_exercised": True,
            "real_runtime_observed": True,
            "completed_native_request_ids": ("native-request-99", "native-request-98"),
            "completed_external_request_ids": ("request-followup", "request-ordinary"),
            "followup_request_id": "native-request-99",
            "ordinary_request_id": "native-request-98",
            "completion_ordering": "followup_before_ordinary",
        },
    )

    with pytest.raises(ValueError, match="retention evidence"):
        adapter.run_controlled_multiturn(
            retention_observer=lambda _runtime, _evidence: False,
        )

    assert run.snapshot()["claims"]["nonterminal_retention"]["status"] == "FAIL"


def test_terminal_cleanup_requires_observed_post_terminal_state() -> None:
    run = _run()
    adapter = _successful_adapter(run)

    with pytest.raises(ValueError, match="terminal cleanup evidence"):
        adapter.run_controlled_multiturn(
            terminal_observer=lambda _runtime, _evidence: False,
        )

    assert run.snapshot()["claims"]["terminal_cleanup"]["status"] == "FAIL"


def test_real_pressure_adapter_requires_exactly_32_completed_requests() -> None:
    run = _run()
    calls: list[int] = []

    def pressure_batch(batch: int) -> dict[str, object]:
        calls.append(batch)
        return {"completed_native_request_ids": tuple(str(index) for index in range(31))}

    adapter = _successful_adapter(run, pressure_batch_executor=pressure_batch)

    with pytest.raises(ValueError, match="exactly 32"):
        adapter.run_pressure_native_cleanup()

    assert calls == [1]
    assert run.snapshot()["scenarios"]["pressure_native_cleanup"]["status"] == "FAIL"


def test_partial_pressure_batch_keeps_validation_incomplete() -> None:
    run = _run()
    adapter = _successful_adapter(
        run,
        pressure_batch_executor=lambda _batch: {
            "completed_native_request_ids": tuple(
                f"pressure-{_batch}-{index}" for index in range(32)
            )
        },
        pressure_observer=lambda: {
            "target_present": True,
            "retention_release_observed": False,
            "plan_validated": False,
            "native_eviction_callback_observed": False,
            "hashes_cleared": False,
        },
    )

    with pytest.raises(ValidationExecutionError, match="evicted_block_id"):
        adapter.run_pressure_native_cleanup()
    assert run.snapshot()["scenarios"]["pressure_native_cleanup"]["status"] == "FAIL"
    assert run.snapshot()["native_cleanup_observations"] == []


def test_mode_claims_require_mode_specific_observed_predicates() -> None:
    run = _run()
    adapter = _successful_adapter(
        run,
        mode_executor=lambda _mode: {"observed": True},
    )

    with pytest.raises(ValueError, match="mode evidence"):
        adapter.run_mode_smokes()

    assert run.snapshot()["claims"]["mode_boundaries"]["status"] == "FAIL"


def test_mode_evidence_accepts_matching_reported_mode() -> None:
    run = _run()
    adapter = _successful_adapter(
        run,
        mode_executor=lambda mode: {**_mode_evidence(mode), "mode": mode},
    )

    assert adapter.run_mode_smokes() is True
    assert set(run.snapshot()["mode_boundaries"]) == {
        "NATIVE",
        "SHADOW",
        "CONTROLLED",
    }


def test_mode_evidence_rejects_mismatched_reported_mode() -> None:
    run = _run()

    def mismatched_mode(mode: str) -> dict[str, object]:
        reported = "SHADOW" if mode == "NATIVE" else mode
        return {**_mode_evidence(mode), "mode": reported}

    adapter = _successful_adapter(run, mode_executor=mismatched_mode)

    with pytest.raises(ValueError, match="mode evidence reported"):
        adapter.run_mode_smokes()
    assert run.snapshot()["claims"]["mode_boundaries"]["status"] == "FAIL"


def test_controlled_pressure_defers_followup_admission_until_after_pressure() -> None:
    class _Provider:
        def estimate(self, _token_count: int) -> tuple[float, InputProvenance]:
            return 0.1, InputProvenance(InputSource.APPROXIMATED, "TEST_PROFILE")

    clock = FakeClock()
    runtime = build_runtime(
        clock=clock,
        prefill_reload_provider=_Provider(),
        default_ttl_seconds=0.0,
        duration_history_threshold=100,
    )
    program = ProgramIdentity("program-validation")
    ordinary_program = ProgramIdentity("ordinary-program")
    first_request = RequestIdentity("r1")
    followup_request = RequestIdentity("r2")
    ordinary_request = RequestIdentity("r3")
    prefix = PrefixIdentity("prefix-r1")
    key = RetentionEntryKey(program, prefix)

    clock.set(0.0)
    runtime.handle(RequestArrived(program, first_request, 0.0))
    clock.set(1.0)
    runtime.record_prefill_context_token_count(
        PrefillContextTokenCountRecord(
            program,
            first_request,
            prefix,
            256,
            InputProvenance(InputSource.OBSERVED),
        )
    )
    runtime.handle(
        BlocksObserved(program, first_request, prefix, (BlockIdentity(7),), 1.0)
    )
    runtime.handle(
        TurnFinished(program, first_request, 1.0, False, next_tool_type="search")
    )
    entry = runtime.retention.snapshot(key)
    assert entry is not None
    assert entry.protected is True
    assert entry.waiting_followup is False
    assert entry.deadline_timestamp == 1.0

    clock.set(1.5)
    runtime.handle(FollowupWaiting(program, followup_request, 1.5))
    admit_followup = _admit_ordinary_and_defer_followup(
        runtime,
        ordinary_program=ordinary_program,
        ordinary_request=ordinary_request,
        followup_program=program,
        followup_request=followup_request,
        ordinary_timestamp=1.5,
    )

    entry = runtime.retention.snapshot(key)
    assert entry is not None
    assert entry.protected is True
    assert entry.waiting_followup is True

    clock.set(2.0)
    admit_followup(2.0)
    entry = runtime.retention.snapshot(key)
    assert entry is not None
    assert entry.protected is False
    assert entry.waiting_followup is False


def test_deferred_followup_evidence_constructs_with_monotonic_timestamps() -> None:
    admission_timestamp = 5.0
    evidence = RequestExecutionEvidence(
        program_id="program-validation",
        request_id="r2",
        native_request_id="r2",
        external_request_id="external-r2",
        token_count=256,
        prefix_id="prefix-r1",
        block_ids=(7,),
        arrival_timestamp=2.0,
        admission_timestamp=admission_timestamp,
        finish_timestamp=_deferred_followup_finish_timestamp(3.0, admission_timestamp),
        terminal=False,
        next_tool_type="search",
    )

    assert evidence.finish_timestamp >= evidence.admission_timestamp


def test_execution_exception_writes_incomplete_artifact(tmp_path: Path) -> None:
    run = _run()
    artifact = tmp_path / "validation.json"
    run.write_artifact(artifact)
    adapter = _successful_adapter(run)

    with pytest.raises(RuntimeError, match="boom"):
        adapter.execute(
            artifact_path=artifact,
            scenario_executor=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )

    assert json.loads(artifact.read_text())['status'] == "incomplete"


def test_default_execution_factory_is_repository_owned_and_callable() -> None:
    module_name, separator, function_name = DEFAULT_EXECUTION_FACTORY.partition(":")
    assert separator == ":"
    module = __import__(module_name, fromlist=[function_name])
    assert callable(getattr(module, function_name))


def test_concrete_factory_returns_all_runtime_boundary_callbacks() -> None:
    module_name, _, function_name = DEFAULT_EXECUTION_FACTORY.partition(":")
    module = __import__(module_name, fromlist=[function_name])
    boundary = getattr(module, function_name)(
        runtime=object(),
        clock=object(),
        run=_run(),
        arguments=SimpleNamespace(),
        observation_helpers=SimpleNamespace(),
        prefill_helpers=SimpleNamespace(),
    )
    assert {
        "request_executor",
        "followup_request_executor",
        "pressure_batch_executor",
        "pressure_observer",
        "mode_executor",
        "scheduler_executor",
    } <= set(boundary)
    assert all(callable(boundary[name]) for name in boundary)


def test_concrete_boundary_replays_shared_controlled_pressure_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.spikes.run_continuum_phase1b_validation_metal as validation

    child = {
        "mode": "CONTROLLED",
        "status": "PASS",
        "pressure_batches": [
            {
                "batch": 1,
                "controlled_runtime_id": "runtime-1",
                "completed_native_request_ids": ("pressure-1",),
            },
            {
                "batch": 2,
                "controlled_runtime_id": "runtime-1",
                "completed_native_request_ids": ("pressure-2",),
            },
        ],
        "pressure_observations": [
            {
                "batch": 1,
                "target_present": True,
                "retention_release_observed": True,
                "plan_validated": True,
                "native_eviction_callback_observed": True,
                "evicted_block_id": 7,
            },
            {
                "batch": 2,
                "target_present": False,
                "retention_release_observed": True,
                "plan_validated": True,
                "native_eviction_callback_observed": True,
                "evicted_block_id": 8,
            },
        ],
        "hook_installed": True,
        "hook_exercised": True,
        "real_runtime_observed": True,
        "followup_request_id": "followup",
        "ordinary_request_id": "ordinary",
        "waiting_request_ids": ("ordinary", "followup"),
        "ordered_request_ids": ("followup", "ordinary"),
        "completed_native_request_ids": ("ordinary", "followup"),
        "completed_external_request_ids": ("ordinary-external", "followup-external"),
        "completion_ordering": "ordinary_before_followup",
    }
    child_calls: list[str] = []

    def fake_child(mode: str, *, arguments: object) -> dict[str, object]:
        child_calls.append(mode)
        return child

    monkeypatch.setattr(validation, "_run_mode_child", fake_child)
    boundary = validation.build_pinned_metal_validation_boundary(
        runtime=object(),
        clock=object(),
        run=_run(),
        arguments=SimpleNamespace(),
        observation_helpers=SimpleNamespace(),
        prefill_helpers=SimpleNamespace(),
    )

    with pytest.raises(ValidationExecutionError, match="before a batch"):
        boundary["pressure_observer"]()

    assert boundary["pressure_batch_executor"](1)["controlled_runtime_id"] == (
        "runtime-1"
    )
    assert boundary["pressure_observer"]()["batch"] == 1
    assert boundary["pressure_batch_executor"](2)["controlled_runtime_id"] == (
        "runtime-1"
    )
    assert boundary["pressure_observer"]()["batch"] == 2

    scheduler = boundary["scheduler_executor"](object(), ())
    assert scheduler["followup_request_id"] == "followup"
    assert scheduler["ordinary_request_id"] == "ordinary"
    assert scheduler["waiting_request_ids"] == ("ordinary", "followup")
    assert scheduler["ordered_request_ids"] == ("followup", "ordinary")
    assert boundary["mode_executor"]("CONTROLLED") is child
    assert child_calls == ["CONTROLLED"]


def test_request_artifact_uses_native_id_and_keeps_external_id_as_metadata() -> None:
    run = _run()
    adapter = _successful_adapter(run)

    assert adapter.run_controlled_multiturn() is True
    requests = run.snapshot()["requests"]
    assert requests[0]["request_id"] == "native-request-1"
    assert requests[0]["native_request_id"] == "native-request-1"
    assert requests[0]["external_request_id"] == "request-1"


def test_mode_executor_uses_fresh_child_process_contract() -> None:
    arguments = SimpleNamespace(
        profile_path=Path("profile.json"),
        output_dir=Path("results"),
        run_id="run-1",
        model="model",
        model_revision="a" * 40,
        tokenizer="model",
        tokenizer_revision="a" * 40,
        gpu_memory_utilization=0.8,
        vllm_metal_source_checkout=Path("/tmp/vllm-metal"),
    )
    calls: list[tuple[object, ...]] = []

    def fake_runner(command, **kwargs):
        calls.append((tuple(command), kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"mode": "SHADOW", "status": "PASS"}) + "\n",
            stderr="",
        )

    evidence = _run_mode_child("SHADOW", arguments=arguments, runner=fake_runner)
    assert evidence["mode"] == "SHADOW"
    assert calls[0][0][0] != "python -c"
    assert "--child-mode" in calls[0][0]


def test_child_failure_is_not_treated_as_mode_success() -> None:
    arguments = SimpleNamespace(
        profile_path=Path("profile.json"),
        output_dir=Path("results"),
        run_id="run-1",
        model="model",
        model_revision="a" * 40,
        tokenizer="model",
        tokenizer_revision="a" * 40,
        gpu_memory_utilization=0.8,
        vllm_metal_source_checkout=Path("/tmp/vllm-metal"),
    )

    def failed_runner(_command, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="child failed")

    with pytest.raises(RuntimeError, match="child failed"):
        _run_mode_child("CONTROLLED", arguments=arguments, runner=failed_runner)


def test_scheduler_claim_requires_real_hook_evidence_not_policy_ordering() -> None:
    run = _run()
    calls: list[tuple[object, object]] = []

    def scheduler_executor(runtime: object, request_ids: object) -> dict[str, object]:
        calls.append((runtime, request_ids))
        return {
            "hook_boundary": "vllm.scheduler.schedule",
            "waiting_request_ids": ("native-request-98", "native-request-99"),
            "ordered_request_ids": ("native-request-99", "native-request-98"),
            "hook_installed": True,
            "hook_exercised": True,
            "real_runtime_observed": True,
            "completed_native_request_ids": ("native-request-98", "native-request-99"),
            "completed_external_request_ids": ("request-ordinary", "request-followup"),
            "followup_request_id": "native-request-99",
            "ordinary_request_id": "native-request-98",
            "completion_ordering": "ordinary_before_followup",
        }

    runtime, clock = _runtime_for_adapter()
    adapter = ValidationExecutionAdapter(
        run=run,
        runtime=runtime,
        clock=clock,
        request_executor=_request_executor,
        pressure_batch_executor=lambda _batch: {
            "completed_native_request_ids": tuple(
                f"pressure-{_batch}-{index}" for index in range(32)
            )
        },
        pressure_observer=dict,
        mode_executor=_mode_evidence,
        scheduler_executor=scheduler_executor,
    )

    assert adapter.run_controlled_multiturn() is True
    assert len(calls) == 1
    evidence = run.snapshot()["scheduler_orders"][0]
    assert evidence["hook_boundary"] == "vllm.scheduler.schedule"
    assert evidence["real_runtime_observed"] is True


def test_scheduler_claim_rejects_missing_real_hook_evidence() -> None:
    run = _run()
    adapter = _successful_adapter(
        run,
        scheduler_executor=lambda _runtime, _request_ids: {
            "ordered_request_ids": ("native-request-2", "native-request-1"),
            "native_schedule_calls": 1,
        },
    )

    with pytest.raises(ValueError, match="scheduler hook evidence"):
        adapter.run_controlled_multiturn()
    assert run.snapshot()["claims"]["scheduler_coordination"]["status"] == "FAIL"


def test_scheduler_claim_requires_real_native_reorder() -> None:
    run = _run()
    adapter = _successful_adapter(
        run,
        scheduler_executor=lambda _runtime, _request_ids: {
            "hook_boundary": "vllm.scheduler.schedule",
            "waiting_request_ids": ("native-request-98", "native-request-99"),
            "ordered_request_ids": ("native-request-98", "native-request-99"),
            "hook_installed": True,
            "hook_exercised": True,
            "real_runtime_observed": True,
            "completed_native_request_ids": ("native-request-98", "native-request-99"),
            "completed_external_request_ids": ("request-ordinary", "request-followup"),
            "followup_request_id": "native-request-99",
            "ordinary_request_id": "native-request-98",
            "completion_ordering": "ordinary_before_followup",
        },
    )

    with pytest.raises(ValueError, match="follow-up-first"):
        adapter.run_controlled_multiturn()


def test_followup_waiting_is_recorded_before_scheduler_hook_evidence() -> None:
    run = _run()
    observed: list[tuple[bool, bool, bool, bool]] = []
    staged_ids: list[tuple[str, ...]] = []

    def scheduler_executor(runtime: object, request_ids: object) -> dict[str, object]:
        staged_ids.append(tuple(item.value for item in request_ids))
        snapshots = runtime.retention.planning_snapshots()
        candidates = runtime.scheduler_candidates(tuple(request_ids))
        ordinary, followup = candidates
        observed.append(
            (
                all(entry.waiting_followup for entry in snapshots),
                followup.is_followup,
                followup.program_is_protected,
                ordinary.is_followup,
            )
        )
        return {
            "hook_boundary": "vllm.scheduler.schedule",
            "waiting_request_ids": ("native-request-98", "native-request-99"),
            "ordered_request_ids": ("native-request-99", "native-request-98"),
            "hook_installed": True,
            "hook_exercised": True,
            "real_runtime_observed": True,
            "completed_native_request_ids": ("native-request-99", "native-request-98"),
            "completed_external_request_ids": ("request-followup", "request-ordinary"),
            "followup_request_id": "native-request-99",
            "ordinary_request_id": "native-request-98",
            "completion_ordering": "followup_before_ordinary",
        }

    adapter = _successful_adapter(run, scheduler_executor=scheduler_executor)
    assert adapter.run_controlled_multiturn() is True
    assert observed == [(True, True, True, False)]
    assert staged_ids == [("native-request-98", "native-request-99")]
    assert any(
        "FOLLOWUP_WAITING" in transition["events"]
        for transition in run.snapshot()["lifecycle_transitions"]
    )


def test_completion_output_external_ids_normalize_to_canonical_native_ids() -> None:
    class _Registry:
        def internal_for_external(self, external_id: str) -> str | None:
            return {"external-1": "native-1", "external-2": "native-2"}.get(
                external_id
            )

    outputs = (
        SimpleNamespace(request_id="external-1"),
        SimpleNamespace(request_id="external-2"),
    )
    external, native = _normalize_child_completion_ids(outputs, _Registry())

    assert external == ("external-1", "external-2")
    assert native == ("native-1", "native-2")


def test_coherent_prefix_snapshot_uses_last_cumulative_hash_length() -> None:
    complete_blocks = [
        {
            "block_id": index,
            "ref_count": 1,
            "native_hash_hex": f"{index:064x}",
            "hash_num_tokens": index * 16,
            "cache_group_id": 0,
            "is_null": False,
        }
        for index in range(1, 17)
    ]
    trailing_partial = {
        "block_id": 17,
        "ref_count": 1,
        "hash_num_tokens": None,
        "cache_group_id": 0,
        "is_null": False,
    }
    historical = {
        "request_blocks": [{
            "request_id": "native-1",
            "availability": "AVAILABLE",
            "block_groups": [[{
                **complete_blocks[0],
                "hash_num_tokens": 16,
            }]],
        }]
    }
    observation = {
        "request_blocks": [
            {
                "request_id": "native-1",
                "availability": "AVAILABLE",
                "block_groups": [complete_blocks + [trailing_partial]],
            }
        ]
    }

    prefix, token_count, block_ids, hashes = _coherent_child_request_snapshot(
        (historical, observation),
        "native-1",
        expected_token_count=TARGET_TOKEN_COUNT,
    )

    last_hash = complete_blocks[-1]["native_hash_hex"]
    assert prefix == f"continuum.prefix.native_hash.v1:{last_hash}"
    assert token_count == TARGET_TOKEN_COUNT
    assert block_ids == tuple(range(1, 17))
    assert hashes == tuple(
        bytes.fromhex(block["native_hash_hex"]) for block in complete_blocks
    )


def test_qualified_target_and_pressure_inputs_use_frozen_lengths() -> None:
    target = _qualified_target_token_ids(TARGET_TOKEN_COUNT, 151_936)
    first_pressure = _qualified_pressure_token_ids(0, 151_936)
    second_pressure = _qualified_pressure_token_ids(1, 151_936)

    assert len(target) == TARGET_TOKEN_COUNT + 1
    assert len(first_pressure) == PRESSURE_TOKEN_COUNT
    assert len(second_pressure) == PRESSURE_TOKEN_COUNT
    assert first_pressure != second_pressure
    assert first_pressure[:16] != target[:16]
    assert all(0 <= token_id < 151_936 for token_id in first_pressure)


def test_controlled_pressure_pool_forces_protected_fallback_after_recycling() -> None:
    base_kwargs = {"model": "pinned-model"}

    kwargs = _controlled_pressure_llm_kwargs(base_kwargs)

    assert base_kwargs == {"model": "pinned-model"}
    assert kwargs == {
        "model": "pinned-model",
        "num_gpu_blocks_override": 48,
        "max_model_len": 528,
        "max_num_batched_tokens": 528,
    }

    # Pinned vLLM reserves one null block.  Once the completed ordinary
    # request is recycled, the same fixed pool still has only 31 ordinary
    # candidates beside R1's 16 protected blocks.  A 512-token prefill needs
    # 32 blocks, so recycling cannot avoid the protected fallback.
    usable_native_blocks = kwargs["num_gpu_blocks_override"] - 1
    protected_target_blocks = TARGET_TOKEN_COUNT // 16
    ordinary_after_recycling = usable_native_blocks - protected_target_blocks
    allocation_demand = PRESSURE_TOKEN_COUNT // 16

    assert ordinary_after_recycling == 31
    assert allocation_demand == 32
    assert ordinary_after_recycling < allocation_demand <= usable_native_blocks


def test_coherent_prefix_snapshot_can_require_one_measured_boundary() -> None:
    block = {
        "block_id": 7,
        "ref_count": 1,
        "native_hash_hex": "aa" * 32,
        "hash_num_tokens": 128,
        "cache_group_id": 0,
        "is_null": False,
    }
    with pytest.raises(ValidationExecutionError, match="coherent") as error:
        _coherent_child_request_snapshot(
            ({
                "request_blocks": [{
                    "request_id": "native-1",
                    "availability": "AVAILABLE",
                    "block_groups": [[block]],
                }]
            },),
            "native-1",
            expected_token_count=TARGET_TOKEN_COUNT,
        )
    message = str(error.value)
    assert "requested_request_id" in message
    assert "group_block_counts" in message
    assert "block_id" in message
    assert "is_null" in message
    assert "native_hash_present" in message
    assert "expected_token_count_mismatch" in message
    assert "hash_num_tokens" in message
    assert "cache_group_id" in message
    assert "ref_count" in message


class _BlockHashToBlockMap:
    def __init__(self, blocks: dict[bytes, object]) -> None:
        self._blocks = blocks
        self.lookups: list[bytes] = []

    def get_one_block(self, key: bytes) -> object | None:
        self.lookups.append(key)
        return self._blocks.get(key)


class _BlockPool:
    def __init__(self, lookup: _BlockHashToBlockMap) -> None:
        self.cached_block_hash_to_block = lookup


def test_target_presence_uses_exact_hash_lookup_on_non_mapping_surface() -> None:
    hashes = (b"hash-a", b"hash-b")
    lookup = _BlockHashToBlockMap({hashes[0]: object(), hashes[1]: object()})
    pool = _BlockPool(lookup)

    assert _read_target_presence((pool,), hashes) is True
    assert lookup.lookups == list(hashes)


def test_target_presence_is_false_when_any_exact_hash_is_missing() -> None:
    hashes = (b"hash-a", b"hash-b")
    lookup = _BlockHashToBlockMap({hashes[0]: object()})

    assert _read_target_presence((_BlockPool(lookup),), hashes) is False


def test_target_presence_fails_closed_without_one_live_block_pool() -> None:
    with pytest.raises(ValidationExecutionError, match="one live native BlockPool"):
        _read_target_presence((), (b"hash-a",))


def test_target_presence_fails_closed_for_multiple_live_block_pools() -> None:
    lookup = _BlockHashToBlockMap({b"hash-a": object()})
    first = _BlockPool(lookup)
    second = _BlockPool(lookup)
    captured: list[object] = []
    _capture_live_block_pool(captured, first)
    _capture_live_block_pool(captured, first)
    _capture_live_block_pool(captured, second)

    with pytest.raises(ValidationExecutionError, match="one live native BlockPool"):
        _read_target_presence(captured, (b"hash-a",))


def test_pressure_phase_keeps_pool_capture_but_stops_heavy_recording() -> None:
    hashes = (b"hash-a",)
    lookup = _BlockHashToBlockMap({hashes[0]: object()})
    pool = _BlockPool(lookup)
    captured: list[object] = []
    recorded: list[object] = []
    observe, enter_pressure = _build_observation_phase_gate(
        recorded.append, captured
    )
    context = SimpleNamespace(target="BlockPool.get_new_blocks", receiver=pool)
    target_hashes = hashes
    target_block_ids = (7,)
    target_prefix_id = "continuum.prefix.native_hash.v1:hash-a"

    observe(context)
    assert recorded == [context]
    assert captured == [pool]
    assert _read_target_presence(captured, target_hashes) is True

    enter_pressure()
    observe(context)

    assert recorded == [context]
    assert captured == [pool]
    assert target_hashes == hashes
    assert target_block_ids == (7,)
    assert target_prefix_id.endswith("hash-a")
    assert _read_target_presence(captured, target_hashes) is True


def test_pressure_phase_rejects_a_different_live_block_pool() -> None:
    first = _BlockPool(_BlockHashToBlockMap({b"hash-a": object()}))
    second = _BlockPool(_BlockHashToBlockMap({b"hash-a": object()}))
    captured: list[object] = []
    observe, enter_pressure = _build_observation_phase_gate(
        lambda _context: None, captured
    )
    observe(SimpleNamespace(target="BlockPool.get_new_blocks", receiver=first))
    enter_pressure()
    observe(SimpleNamespace(target="BlockPool.get_new_blocks", receiver=second))

    with pytest.raises(ValidationExecutionError, match="one live native BlockPool"):
        _read_target_presence(captured, (b"hash-a",))


def test_controlled_request_roles_ignore_submission_positions() -> None:
    submitted = ("retained-first", "ordinary", "followup")

    followup, ordinary = _controlled_request_roles(
        followup_request_id=submitted[2],
        ordinary_request_id=submitted[1],
    )

    assert followup == "followup"
    assert ordinary == "ordinary"


def test_generic_remove_activity_does_not_claim_logical_release() -> None:
    class _Result:
        selection_plan = None

    class _Delegate:
        def apply_pressure(self, **kwargs: object) -> _Result:
            callback = kwargs["remove_selected"]
            assert callable(callback)
            callback((7,))
            return _Result()

        def observe_native_eviction(self, _block_id: object) -> None:
            return None

    proxy = _EvictionEvidenceProxy(_Delegate())
    proxy.apply_pressure(remove_selected=lambda _block_ids: None)

    assert proxy.remove_selected_calls == 1
    assert proxy.release_entry_keys == []
    assert proxy.release_effects == []


def test_pressure_release_effect_serializes_block_identities_as_ints() -> None:
    key = RetentionEntryKey(
        ProgramIdentity("program-a"),
        PrefixIdentity("prefix-a"),
    )
    effect = PressureReleaseEffect(
        entry_key=key,
        newly_eligible_block_ids=(BlockIdentity(7), BlockIdentity(8)),
    )

    class _Delegate:
        def apply_pressure(self, **_kwargs: object) -> object:
            preparation = SimpleNamespace(
                ordinary_expired_entries=(),
                pressure_releases=(effect,),
            )
            return SimpleNamespace(
                selection_plan=SimpleNamespace(preparation=preparation)
            )

        def observe_native_eviction(self, _block_id: object) -> None:
            return None

    proxy = _EvictionEvidenceProxy(_Delegate())
    proxy.apply_pressure()

    assert proxy.release_effects == [
        {
            "program_id": "program-a",
            "prefix_id": "prefix-a",
            "newly_eligible_block_ids": [7, 8],
        }
    ]


def test_two_pressure_batches_use_64_fresh_native_ids() -> None:
    run = _run()
    seen: list[tuple[str, ...]] = []
    observations = iter((True, False))

    def batch(batch_number: int) -> dict[str, object]:
        ids = tuple(
            f"pressure-{batch_number}-{index}" for index in range(32)
        )
        seen.append(ids)
        return {"completed_native_request_ids": ids}

    adapter = _successful_adapter(
        run,
        pressure_batch_executor=batch,
        pressure_observer=lambda: {
            "target_present": next(observations),
            "retention_release_observed": True,
            "plan_validated": True,
            "native_eviction_callback_observed": True,
            "evicted_block_id": 7,
        },
    )

    assert adapter.run_pressure_native_cleanup() is True
    assert len(seen) == 2
    assert len({request_id for ids in seen for request_id in ids}) == 64


def test_missing_pressure_evidence_fails_closed() -> None:
    run = _run()
    adapter = _successful_adapter(
        run,
        pressure_observer=lambda: {
            "target_present": False,
            "retention_release_observed": True,
            "plan_validated": True,
            "native_eviction_callback_observed": True,
        },
    )

    with pytest.raises(ValidationExecutionError, match="evicted_block_id"):
        adapter.run_pressure_native_cleanup()


def test_real_pressure_batch_wrapper_requires_exactly_32_results() -> None:
    assert _require_real_pressure_batch(
        lambda: tuple(f"request-{index}" for index in range(32))
    ) == tuple(f"request-{index}" for index in range(32))
    with pytest.raises(ValueError, match="exactly 32"):
        _require_real_pressure_batch(lambda: tuple(str(index) for index in range(31)))


def test_concrete_boundary_is_lazy_and_does_not_import_metal_at_module_import() -> None:
    module = __import__(
        "scripts.spikes.run_continuum_phase1b_validation_metal",
        fromlist=["build_pinned_metal_validation_boundary"],
    )
    assert callable(module.build_pinned_metal_validation_boundary)
    assert "vllm" not in __import__("sys").modules
