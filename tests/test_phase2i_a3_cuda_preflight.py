from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from kvopt.workload import phase2i_a3_cuda_preflight as module
from scripts.spikes import run_phase2i_a3_cuda_preflight as runner


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _source(tmp_path: Path) -> tuple[Path, Path, Path]:
    requests = [
        {
            "program_id": "program",
            "request_id": f"request-{index}",
            "turn_index": index,
            "planned_arrival_offset_seconds": 0.0,
            "prompt": "prompt",
            "prefix_prompt": "",
            "is_terminal": False,
            "next_tool_type": "gap",
            "tool_gap_seconds": 0.0,
            "kind": "turn",
        }
        for index in range(180)
    ]
    trace = tmp_path / "source.trace.json"
    _write(
        trace,
        {
            "schema_version": "phase2.trace.v1",
            "trace_id": "phase2h-hr02-short-gap-long-context",
            "allow_incomplete_programs": True,
            "requests": requests,
            "pressure_stages": [],
        },
    )
    replay = {row["request_id"]: [index, index + 1] for index, row in enumerate(requests)}
    submissions = {
        key: hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for key, value in replay.items()
    }
    pressure_stages = {
        boundary: {
            "stage_id": boundary.removeprefix("pressure:"),
            "prompt": boundary,
            "max_requests": 1,
            "stop_on_forced_release": False,
        }
        for boundary in module.PRESSURE_BOUNDARIES
    }
    config = tmp_path / "source.config.json"
    _write(
        config,
        {
            "schema_version": "phase2.config.v1",
            "campaign_kind": "phase2h_history_rich_native_smoke",
            "runtime_mode": "vllm-cuda-observability",
            "backend_factory": "factory:build",
            "backend_revision": "phase2h-history-rich-cuda-v1",
            "model": {
                "name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
                "revision": module.MODEL_REVISION,
            },
            "tokenizer": {
                "name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
                "revision": module.MODEL_REVISION,
            },
            "generation": {"max_new_tokens": 1, "temperature": 0.0},
            "cache": {"block_override": 2048, "block_size": 16},
            "batching": {"max_concurrent_requests": 2},
            "pressure": {
                "initial_shortage_blocks": 128,
                "required_blocks": 379,
                "safety_ceiling": 1,
            },
            "seed": 20261121,
            "observe": True,
            "policy": "continuum-a1-entry-native-lru",
            "trace": trace.name,
            "controlled_sparse_replay": {
                "logical_sequence_sha256": "timeline-sha",
            },
            "backend_options": {
                "phase2g_release_policy": "A1",
                "phase2g_block_policy": "A0",
                "replay_token_ids_by_request": replay,
                "expected_native_submission_sha256_by_request": submissions,
                "controlled_pressure_stages_by_boundary": pressure_stages,
                "pressure_token_ids_by_stage": {
                    stage["stage_id"]: [index, index + 1]
                    for index, stage in enumerate(pressure_stages.values())
                },
                "prefill_profile_path": "old-profile.json",
            },
        },
    )
    profile = tmp_path / "profile.json"
    _write(profile, {"schema_version": "profile"})
    return config, trace, profile


def _predecessor(path: Path, config: Path, trace: Path, profile: Path) -> Path:
    value = json.loads(config.read_text(encoding="utf-8"))
    backend = value["backend_options"]
    freeze = {
        "schema_version": module.FIRST_PREFLIGHT_FREEZE_SCHEMA,
        "run_id": module.FIRST_PREFLIGHT_RUN_ID,
        "git_sha": "first-git-sha",
        "source": {
            "config_sha256": module._sha(config),
            "trace_sha256": module._sha(trace),
            "profile_sha256": module._sha(profile),
            "explicit_token_ids_sha256": module._canonical_sha(
                backend["replay_token_ids_by_request"]
            ),
            "pressure_token_ids_sha256": module._canonical_sha(
                backend["pressure_token_ids_by_stage"]
            ),
            "logical_sequence_sha256": value["controlled_sparse_replay"][
                "logical_sequence_sha256"
            ],
        },
    }
    report = {
        "schema_version": "phase2i.a3_target_cuda_native_preflight.v1",
        "status": "FAIL_CLOSED",
        "run_id": module.FIRST_PREFLIGHT_RUN_ID,
        "run_status": "success",
        "git_sha": "first-git-sha",
        "freeze_record_sha256": module._canonical_sha(freeze),
    }
    run = {"run_id": module.FIRST_PREFLIGHT_RUN_ID, "status": "success"}
    with tarfile.open(path, "w:gz") as archive:
        for name, value in (
            ("artifacts/first/freeze-record.json", freeze),
            ("artifacts/first/native-preflight-report.json", report),
            (f"artifacts/first/runs/{module.FIRST_PREFLIGHT_RUN_ID}/run.json", run),
        ):
            raw = (json.dumps(value, sort_keys=True) + "\n").encode()
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    return path


def _actual_v1_predecessor(
    path: Path, config: Path, trace: Path, profile: Path
) -> Path:
    complete = _predecessor(path.with_name("complete-v1.tar.gz"), config, trace, profile)
    freeze, _members, _report, run = module._load_predecessor_evidence(complete)
    offline_report = {
        "schema_version": "phase2i.a3_native_static_preflight.v1",
        "status": "FAIL_CLOSED",
        "gates": {"O": {"status": "FAIL"}},
    }
    with tarfile.open(path, "w:gz") as archive:
        for name, value in (
            ("artifacts/first/freeze-record.json", freeze),
            ("artifacts/first/offline-gate-diagnostic.json", offline_report),
            (f"artifacts/first/runs/{module.FIRST_PREFLIGHT_RUN_ID}/run.json", run),
        ):
            raw = (json.dumps(value, sort_keys=True) + "\n").encode()
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))
    return path


def test_materialize_changes_only_authorized_runtime_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "abc123",
    )
    output = tmp_path / "prepared"
    predecessor = _predecessor(
        tmp_path / "predecessor.tar.gz", config, trace, profile
    )

    manifest = module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        predecessor_archive_path=predecessor,
        output_dir=output,
        repository=tmp_path,
    )

    derived = json.loads(
        (output / f"{module.RUN_ID}.config.json").read_text(encoding="utf-8")
    )
    assert manifest["git_sha"] == "abc123"
    assert manifest["execution_authorized"] is False
    assert manifest["predecessor"]["status"] == "FAIL_CLOSED"
    assert manifest["predecessor"]["archive_sha256"] == module._sha(predecessor)
    request = json.loads(
        (output / "m1-authorization-request.json").read_text(encoding="utf-8")
    )
    assert request["execution_authorized"] is False
    assert derived["campaign_kind"] == "phase2i_a3_native_integration"
    assert derived["backend_options"]["phase2g_release_policy"] == "A3"
    assert derived["backend_options"]["phase2g_block_policy"] == "A0"
    assert derived["cache"] == {"block_override": 2048, "block_size": 16}
    assert derived["pressure"] == {
        "initial_shortage_blocks": 128,
        "required_blocks": 379,
        "safety_ceiling": 1,
    }
    assert (output / "hr02-short-gap-long-context.trace.json").read_bytes() == trace.read_bytes()
    copied_profile = output / "prefill-profile.json"
    assert copied_profile.read_bytes() == profile.read_bytes()
    assert derived["backend_options"]["prefill_profile_path"] == str(
        copied_profile.resolve()
    )
    assert manifest["derived"]["profile_sha256"] == module._sha(copied_profile)


def test_materialize_admin_retry_binds_failed_environment_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "new-head",
    )
    predecessor = _predecessor(
        tmp_path / "predecessor.tar.gz", config, trace, profile
    )
    prior_freeze = {
        "schema_version": "phase2i.a3_target_cuda_replacement_preflight_freeze.v2",
        "run_id": module.RUN_ID,
        "git_sha": "old-head",
    }
    admin_archive = tmp_path / "environment-failure.tar.gz"
    with tarfile.open(admin_archive, "w:gz") as archive:
        for name, value in (
            ("inputs/freeze-record.json", prior_freeze),
            (
                f"outputs/runs/{module.RUN_ID}/run.json",
                {"run_id": module.RUN_ID, "status": "failed"},
            ),
            ("outputs/execution-envelope.json", {"status": "FAILED"}),
        ):
            raw = (json.dumps(value, sort_keys=True) + "\n").encode()
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))

    output = tmp_path / "admin-prepared"
    result = module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        predecessor_archive_path=predecessor,
        output_dir=output,
        repository=tmp_path,
        run_id=module.ADMIN_RETRY_RUN_ID,
        administrative_predecessor_archive_path=admin_archive,
    )

    request = json.loads((output / "m1-authorization-request.json").read_text())
    assert result["run_id"] == module.ADMIN_RETRY_RUN_ID
    assert result["git_sha"] == "new-head"
    assert result["administrative_retry"]["original_git_sha"] == "old-head"
    assert result["administrative_retry"]["failed_archive_sha256"] == module._sha(
        admin_archive
    )
    assert request["administrative_failed_archive_sha256"] == module._sha(
        admin_archive
    )

    retry_02_archive = tmp_path / "retry-01-environment-failure.tar.gz"
    with tarfile.open(retry_02_archive, "w:gz") as archive:
        for name, raw in (
            ("inputs/freeze-record.json", (output / "freeze-record.json").read_bytes()),
            (
                f"outputs/runs/{module.ADMIN_RETRY_RUN_ID}/run.json",
                (json.dumps({"run_id": module.ADMIN_RETRY_RUN_ID, "status": "failed"}) + "\n").encode(),
            ),
            (
                "outputs/execution-envelope.json",
                (json.dumps({"status": "FAILED"}) + "\n").encode(),
            ),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            archive.addfile(member, io.BytesIO(raw))

    retry_02_output = tmp_path / "admin-retry-02-prepared"
    retry_02 = module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        predecessor_archive_path=predecessor,
        output_dir=retry_02_output,
        repository=tmp_path,
        run_id=module.ADMIN_RETRY_02_RUN_ID,
        administrative_predecessor_archive_path=retry_02_archive,
    )
    assert retry_02["run_id"] == module.ADMIN_RETRY_02_RUN_ID
    assert retry_02["administrative_retry"]["original_run_id"] == (
        module.ADMIN_RETRY_RUN_ID
    )


def test_materialize_rejects_pressure_or_explicit_token_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    value = json.loads(config.read_text(encoding="utf-8"))
    value["pressure"]["required_blocks"] = 378
    _write(config, value)
    monkeypatch.setattr(module, "_git", lambda *_args: "abc123")
    predecessor = _predecessor(
        tmp_path / "predecessor.tar.gz", config, trace, profile
    )

    with pytest.raises(ValueError, match="pressure geometry drifted"):
        module.materialize_preflight(
            source_config_path=config,
            source_trace_path=trace,
            profile_path=profile,
            predecessor_archive_path=predecessor,
            output_dir=tmp_path / "prepared",
            repository=tmp_path,
        )


def test_verify_freeze_rejects_git_or_file_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "abc123",
    )
    output = tmp_path / "prepared"
    predecessor = _predecessor(
        tmp_path / "predecessor.tar.gz", config, trace, profile
    )
    module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        predecessor_archive_path=predecessor,
        output_dir=output,
        repository=tmp_path,
    )
    (output / "hr02-short-gap-long-context.trace.json").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="trace_sha256"):
        module._verify_freeze(output, tmp_path)


def test_verify_freeze_rejects_predecessor_archive_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "abc123",
    )
    predecessor = _predecessor(
        tmp_path / "predecessor.tar.gz", config, trace, profile
    )
    output = tmp_path / "prepared"
    module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        predecessor_archive_path=predecessor,
        output_dir=output,
        repository=tmp_path,
    )
    predecessor.write_bytes(b"mutated")

    with pytest.raises(ValueError, match="predecessor archive binding mismatch"):
        module._verify_freeze(output, tmp_path)


def test_materialize_rejects_archive_without_original_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(module, "_git", lambda *_args: "abc123")
    predecessor = tmp_path / "predecessor.tar.gz"
    with tarfile.open(predecessor, "w:gz") as archive:
        raw = b"{}\n"
        member = tarfile.TarInfo("unrelated.json")
        member.size = len(raw)
        archive.addfile(member, io.BytesIO(raw))

    with pytest.raises(ValueError, match="authoritative freeze record"):
        module.materialize_preflight(
            source_config_path=config,
            source_trace_path=trace,
            profile_path=profile,
            predecessor_archive_path=predecessor,
            output_dir=tmp_path / "prepared",
            repository=tmp_path,
        )


def test_materialize_rejects_freeze_only_archive_without_failed_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(module, "_git", lambda *_args: "abc123")
    complete = _predecessor(tmp_path / "complete.tar.gz", config, trace, profile)
    freeze = module._load_predecessor_evidence(complete)[0]
    predecessor = tmp_path / "freeze-only.tar.gz"
    with tarfile.open(predecessor, "w:gz") as archive:
        raw = json.dumps(freeze).encode()
        member = tarfile.TarInfo("freeze-record.json")
        member.size = len(raw)
        archive.addfile(member, io.BytesIO(raw))

    with pytest.raises(ValueError, match="failed Native report"):
        module.materialize_preflight(
            source_config_path=config,
            source_trace_path=trace,
            profile_path=profile,
            predecessor_archive_path=predecessor,
            output_dir=tmp_path / "prepared",
            repository=tmp_path,
        )


def test_materialize_accepts_actual_v1_offline_failure_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "abc123",
    )
    predecessor = _actual_v1_predecessor(
        tmp_path / "actual-v1.tar.gz", config, trace, profile
    )

    result = module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        predecessor_archive_path=predecessor,
        output_dir=tmp_path / "prepared",
        repository=tmp_path,
    )

    assert result["predecessor"]["status"] == "FAIL_CLOSED"


def test_authorization_is_independent_bound_and_consumed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "abc123",
    )
    predecessor = _predecessor(
        tmp_path / "predecessor.tar.gz", config, trace, profile
    )
    output = tmp_path / "prepared"
    freeze = module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        predecessor_archive_path=predecessor,
        output_dir=output,
        repository=tmp_path,
    )
    request = json.loads(
        (output / "m1-authorization-request.json").read_text(encoding="utf-8")
    )
    authorization = {
        **request,
        "schema_version": module.AUTHORIZATION_SCHEMA,
        "execution_authorized": True,
        "authorization_id": "m1-approved-replacement-02",
    }
    authorization_path = tmp_path / "m1-authorization.json"
    _write(authorization_path, authorization)

    verified, ledger, authorization_sha = module._verify_authorization(
        authorization_path,
        input_dir=output,
        freeze=freeze,
    )
    module._consume_authorization(
        ledger,
        authorization=verified,
        authorization_sha256=authorization_sha,
        output_root=tmp_path / "run-output-a",
    )
    with pytest.raises(RuntimeError, match="already consumed"):
        module._consume_authorization(
            ledger,
            authorization=verified,
            authorization_sha256=authorization_sha,
            output_root=tmp_path / "run-output-b",
        )
    changed = dict(authorization)
    changed["authorization_id"] = "m1-approved-replacement-02-renamed"
    changed_path = tmp_path / "m1-authorization-renamed.json"
    _write(changed_path, changed)
    verified_again, same_ledger, changed_sha = module._verify_authorization(
        changed_path, input_dir=output, freeze=freeze
    )
    assert same_ledger == ledger
    with pytest.raises(RuntimeError, match="already consumed"):
        module._consume_authorization(
            same_ledger,
            authorization=verified_again,
            authorization_sha256=changed_sha,
            output_root=tmp_path / "run-output-c",
        )


def test_authorization_rejects_unapproved_or_mismatched_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "abc123",
    )
    predecessor = _predecessor(
        tmp_path / "predecessor.tar.gz", config, trace, profile
    )
    output = tmp_path / "prepared"
    freeze = module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        predecessor_archive_path=predecessor,
        output_dir=output,
        repository=tmp_path,
    )
    authorization = json.loads(
        (output / "m1-authorization-request.json").read_text(encoding="utf-8")
    )
    authorization.update(
        {
            "schema_version": module.AUTHORIZATION_SCHEMA,
            "authorization_id": "not-approved",
        }
    )
    authorization_path = tmp_path / "m1-authorization.json"
    _write(authorization_path, authorization)

    with pytest.raises(ValueError, match="execution_authorized"):
        module._verify_authorization(
            authorization_path,
            input_dir=output,
            freeze=freeze,
        )


def test_authorization_rejects_binding_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "abc123",
    )
    predecessor = _predecessor(tmp_path / "predecessor.tar.gz", config, trace, profile)
    output = tmp_path / "prepared"
    freeze = module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        predecessor_archive_path=predecessor,
        output_dir=output,
        repository=tmp_path,
    )
    authorization = json.loads((output / "m1-authorization-request.json").read_text())
    authorization.update(
        {
            "schema_version": module.AUTHORIZATION_SCHEMA,
            "execution_authorized": True,
            "authorization_id": "m1-authentic",
        }
    )
    authorization["git_sha"] = "tampered"
    path = tmp_path / "tampered.json"
    _write(path, authorization)

    with pytest.raises(ValueError, match="git_sha"):
        module._verify_authorization(path, input_dir=output, freeze=freeze)


def test_target_environment_is_exact_and_fail_closed() -> None:
    environment = {**module.EXPECTED_ENVIRONMENT, "cuda_available": True}
    module._validate_environment(environment)

    for field in module.EXPECTED_ENVIRONMENT:
        drifted = dict(environment)
        drifted[field] = "drifted"
        with pytest.raises(RuntimeError, match=field):
            module._validate_environment(drifted)


def test_right_censoring_is_derived_from_events() -> None:
    config = {
        "backend_options": {
            "w1b_right_censored_end_request_ids": ["request-a", "request-b"]
        }
    }
    complete = (
        {
            "event_type": "W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED",
            "request_id": "request-a",
        },
        {
            "event_type": "W1B_RIGHT_CENSORED_REPLAY_WINDOW_ENDED",
            "request_id": "request-b",
        },
    )
    assert module._right_censoring_evidence(config, complete)[
        "right_censoring_preserved"
    ] is True
    assert module._right_censoring_evidence(config, complete[:1])[
        "right_censoring_preserved"
    ] is False


def test_execution_wrapper_enforces_timeout_grace_and_archives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _TimedOutProcess:
        def __init__(self) -> None:
            self.wait_count = 0
            self.signals: list[int] = []
            self.pid = 4242

        def wait(self, *, timeout: int | None = None) -> int:
            self.wait_count += 1
            if self.wait_count == 1:
                raise runner.subprocess.TimeoutExpired("phase2i", timeout)
            return 130

    process = _TimedOutProcess()
    popen_kwargs: dict[str, object] = {}

    def fake_popen(_command, **kwargs):
        popen_kwargs.update(kwargs)
        return process

    monkeypatch.setattr(
        runner.subprocess, "Popen", fake_popen
    )
    monkeypatch.setattr(
        runner.os,
        "killpg",
        lambda pid, value: process.signals.append(value) if pid == process.pid else None,
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        runner,
        "_archive_execution",
        lambda **kwargs: captured.update(kwargs) or tmp_path / "evidence.tar.gz",
    )
    monkeypatch.setattr(runner, "TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(runner, "TERMINATION_GRACE_SECONDS", 2)
    arguments = SimpleNamespace(
        input_dir=tmp_path / "inputs",
        output_root=tmp_path / "outputs",
        authorization_record=tmp_path / "authorization.json",
        repository=tmp_path,
    )
    arguments.input_dir.mkdir()
    _write(arguments.input_dir / "freeze-record.json", {"run_id": module.RUN_ID})

    assert runner._run_bounded(arguments) == 130
    assert process.signals == [runner.signal.SIGINT]
    assert popen_kwargs["start_new_session"] is True
    assert len(popen_kwargs["pass_fds"]) == 1
    assert captured["outcome"]["status"] == "TIMEOUT"
    assert captured["outcome"]["termination_grace_seconds"] == 2


def test_internal_capability_cannot_be_replaced_by_environment_variable(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHASE2I_BOUNDED_PARENT_TOKEN", "forged")
    read_descriptor, write_descriptor = runner.os.pipe()
    with runner.os.fdopen(write_descriptor, "wb") as stream:
        stream.write(b'{}')
    with pytest.raises(RuntimeError, match="parent binding failed"):
        module.read_bounded_parent_capability(read_descriptor)


def test_timeout_kills_entire_process_group_after_grace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _HungProcess:
        pid = 5151

        def __init__(self) -> None:
            self.wait_count = 0

        def wait(self, *, timeout=None):
            self.wait_count += 1
            if self.wait_count <= 2:
                raise runner.subprocess.TimeoutExpired("phase2i", timeout)
            return -9

    process = _HungProcess()
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(runner.os, "killpg", lambda pid, signal: signals.append((pid, signal)))
    monkeypatch.setattr(runner, "TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(runner, "TERMINATION_GRACE_SECONDS", 1)
    monkeypatch.setattr(
        runner,
        "_archive_execution",
        lambda **_kwargs: tmp_path / "evidence.tar.gz",
    )
    arguments = SimpleNamespace(
        input_dir=tmp_path / "inputs",
        output_root=tmp_path / "outputs",
        authorization_record=tmp_path / "authorization.json",
        repository=tmp_path,
    )
    arguments.input_dir.mkdir()
    _write(arguments.input_dir / "freeze-record.json", {"run_id": module.RUN_ID})

    assert runner._run_bounded(arguments) == -9
    assert signals == [
        (process.pid, runner.signal.SIGINT),
        (process.pid, runner.signal.SIGKILL),
    ]


def test_direct_import_cannot_call_gpu_executor_without_parent_capability(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError, match="bounded_capability"):
        module.run_preflight(
            input_dir=tmp_path / "inputs",
            output_root=tmp_path / "outputs",
            repository=tmp_path,
            authorization_path=tmp_path / "authorization.json",
        )


def test_atomic_archive_rejects_conflict_and_removes_interrupted_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "outputs"
    authorization = tmp_path / "authorization.json"
    inputs.mkdir()
    _write(inputs / "freeze-record.json", {"freeze": True})
    _write(authorization, {"authorized": True})
    final = tmp_path / "outputs-evidence.tar.gz"
    final.write_bytes(b"occupied")
    with pytest.raises(FileExistsError):
        runner._archive_execution(
            input_dir=inputs,
            output_root=outputs,
            authorization_record=authorization,
            outcome={"status": "FAILED"},
        )

    final.unlink()
    original_add = tarfile.TarFile.add
    calls = 0

    def interrupted_add(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("compression interrupted")
        return original_add(self, *args, **kwargs)

    monkeypatch.setattr(tarfile.TarFile, "add", interrupted_add)
    with pytest.raises(OSError, match="compression interrupted"):
        runner._archive_execution(
            input_dir=inputs,
            output_root=outputs,
            authorization_record=authorization,
            outcome={"status": "FAILED"},
        )
    assert not final.exists()
    assert not tuple(tmp_path.glob(".outputs-evidence.tar.gz.tmp-*"))
