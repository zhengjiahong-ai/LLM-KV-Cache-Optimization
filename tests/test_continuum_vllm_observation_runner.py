from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from kvopt.continuum import ProgramIdentity, RequestIdentity
from scripts.spikes import run_continuum_vllm_observation as runner_module
from scripts.spikes.continuum_vllm_scenarios import (
    SCENARIO_NAMES,
    ScenarioConfig,
    build_scenario,
    materialize_prompts,
)
from scripts.spikes.run_continuum_vllm_observation import (
    REQUIRED_OUTPUT_FILENAMES,
    EvidenceWriter,
    HookBinding,
    NativeObservationRecorder,
    ObservationContext,
    ObservationHookSet,
    ObservationPhase,
    ProgramRequestRegistry,
    RunnerError,
    build_llm_kwargs,
    build_vllm_hook_bindings,
    execute_plan,
    parse_args,
    require_observation_topology,
    verify_runtime_identity,
)

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/spikes/run_continuum_observation_metal.sh"


def launcher_args(tmp_path: Path) -> list[str]:
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    source_checkout = tmp_path / "vllm-metal-source"
    source_checkout.mkdir()
    return [
        "bash",
        str(LAUNCHER),
        "--dry-run",
        "--python",
        sys.executable,
        "--scenario",
        "environment_smoke",
        "--run-id",
        "run-1",
        "--model",
        "Qwen/Qwen2.5-0.5B-Instruct",
        "--model-revision",
        "1" * 40,
        "--tokenizer",
        "Qwen/Qwen2.5-0.5B-Instruct",
        "--tokenizer-revision",
        "2" * 40,
        "--output-dir",
        str(output_dir),
        "--observer-mode",
        "off",
        "--gpu-memory-utilization",
        "0.30",
        "--vllm-metal-source-checkout",
        str(source_checkout),
        "--pressure-request-count",
        "7",
        "--pressure-prompt-tokens",
        "96",
        "--max-tokens",
        "3",
    ]


def test_launcher_dry_run_renders_native_metal_command(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        launcher_args(tmp_path),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    argv = shlex.split(completed.stdout)
    assert argv[0] == "env"
    assert f"PYTHONPATH={ROOT / 'src'}:{ROOT}" in argv
    assert "VLLM_ENABLE_V1_MULTIPROCESSING=0" in argv
    assert "VLLM_METAL_USE_PAGED_ATTENTION=1" in argv
    assert "VLLM_METAL_MEMORY_FRACTION=auto" in argv
    assert "VLLM_MLX_DEVICE=gpu" in argv
    assert "VLLM_HOST_IP=127.0.0.1" in argv
    assert any(value.startswith("KVOPT_TASK3_COMMIT_SHA=") for value in argv)
    assert any(value.startswith("KVOPT_TASK3_WORKTREE_CLEAN=") for value in argv)
    assert sys.executable in argv
    assert argv[argv.index("-m") + 1] == "scripts.spikes.run_continuum_vllm_observation"
    assert argv[argv.index("--model-revision") + 1] == "1" * 40
    assert argv[argv.index("--tokenizer-revision") + 1] == "2" * 40
    assert argv[argv.index("--vllm-metal-source-checkout") + 1] == str(
        tmp_path / "vllm-metal-source"
    )
    assert argv[argv.index("--pressure-request-count") + 1] == "7"
    assert argv[argv.index("--pressure-prompt-tokens") + 1] == "96"
    assert argv[argv.index("--max-tokens") + 1] == "3"
    assert "docker" not in argv
    assert "nvidia-smi" not in argv
    assert argv[-2:] == ["2>", str(tmp_path / "results/run-1/stderr.log")]


def test_launcher_owns_command_and_stderr_evidence(tmp_path: Path) -> None:
    args = launcher_args(tmp_path)
    args.remove("--dry-run")
    fake_python = tmp_path / "fake-python"
    fake_python.write_text("#!/bin/sh\nprintf 'native diagnostic\\n' >&2\n", encoding="utf-8")
    fake_python.chmod(0o755)
    args[args.index("--python") + 1] = str(fake_python)

    completed = subprocess.run(
        args,
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    run_directory = tmp_path / "results/run-1"
    command = run_directory.joinpath("commands.txt").read_text(encoding="utf-8")
    assert "VLLM_ENABLE_V1_MULTIPROCESSING=0" in command
    assert "VLLM_METAL_USE_PAGED_ATTENTION=1" in command
    assert "VLLM_METAL_MEMORY_FRACTION=auto" in command
    assert "VLLM_MLX_DEVICE=gpu" in command
    assert "VLLM_HOST_IP=127.0.0.1" in command
    assert str(fake_python) in command
    assert run_directory.joinpath("stderr.log").read_text(encoding="utf-8") == (
        "native diagnostic\n"
    )
    assert completed.stderr == ""


def test_launcher_requires_immutable_model_revision(tmp_path: Path) -> None:
    args = launcher_args(tmp_path)
    index = args.index("--model-revision")
    del args[index : index + 2]

    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "--model-revision is required" in completed.stderr


def test_launcher_requires_immutable_tokenizer_revision(tmp_path: Path) -> None:
    args = launcher_args(tmp_path)
    index = args.index("--tokenizer-revision")
    del args[index : index + 2]

    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "--tokenizer-revision is required" in completed.stderr


@pytest.mark.parametrize("option", ["--model-revision", "--tokenizer-revision"])
def test_launcher_rejects_mutable_hugging_face_revision(
    tmp_path: Path,
    option: str,
) -> None:
    args = launcher_args(tmp_path)
    args[args.index(option) + 1] = "main"

    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "must be a lowercase 40-hex commit" in completed.stderr


def test_disabled_hook_set_does_not_replace_native_method() -> None:
    class Native:
        def method(self) -> str:
            return "native"

    original = Native.method
    binding = HookBinding(Native, "method", "Native.method", before=True)

    with ObservationHookSet((binding,), lambda context: None, enabled=False):
        assert Native.method is original

    assert Native.method is original


def test_enabled_hook_preserves_arguments_and_return_identity() -> None:
    calls: list[tuple[object, object]] = []
    contexts: list[ObservationContext] = []
    result = object()

    class Native:
        def method(self, value: object, *, flag: object) -> object:
            calls.append((value, flag))
            return result

    value = object()
    flag = object()
    binding = HookBinding(
        Native,
        "method",
        "Native.method",
        before=True,
        after=True,
    )

    with ObservationHookSet((binding,), contexts.append, enabled=True):
        observed_result = Native().method(value, flag=flag)

    assert observed_result is result
    assert calls == [(value, flag)]
    assert calls[0][0] is value
    assert calls[0][1] is flag
    assert [context.phase for context in contexts] == [
        ObservationPhase.BEFORE_NATIVE_CALL,
        ObservationPhase.AFTER_NATIVE_RETURN,
    ]
    assert contexts[0].args == (value,)
    assert contexts[0].kwargs["flag"] is flag
    assert contexts[1].native_result is result


def test_native_exception_identity_is_preserved_and_hook_is_restored() -> None:
    error = LookupError("native failed")
    contexts: list[ObservationContext] = []

    class Native:
        def method(self) -> None:
            raise error

    original = Native.method
    binding = HookBinding(Native, "method", "Native.method", after=True)

    with (
        pytest.raises(LookupError) as caught,
        ObservationHookSet((binding,), contexts.append, enabled=True),
    ):
        Native().method()

    assert caught.value is error
    assert Native.method is original
    assert [context.phase for context in contexts] == [
        ObservationPhase.AFTER_NATIVE_EXCEPTION
    ]
    assert contexts[0].native_exception is error


def test_hooks_restore_when_body_raises() -> None:
    class Native:
        def method(self) -> str:
            return "native"

    original = Native.method
    binding = HookBinding(Native, "method", "Native.method", before=True)

    with (
        pytest.raises(RuntimeError, match="body failed"),
        ObservationHookSet((binding,), lambda context: None, enabled=True),
    ):
        assert Native.method is not original
        raise RuntimeError("body failed")

    assert Native.method is original


def test_observer_exception_emits_error_without_changing_native_behavior() -> None:
    diagnostics: list[dict[str, str]] = []
    result = object()

    class Native:
        def method(self) -> object:
            return result

    def observer(context: ObservationContext) -> None:
        raise RuntimeError(f"observer failed at {context.phase.value}")

    binding = HookBinding(Native, "method", "Native.method", before=True, after=True)

    hook_set = ObservationHookSet(
        (binding,),
        observer,
        enabled=True,
        error_sink=diagnostics.append,
    )
    with hook_set:
        observed_result = Native().method()

    assert observed_result is result
    assert diagnostics == [
        {
            "event_type": "OBSERVER_ERROR",
            "target": "Native.method",
            "phase": "BEFORE_NATIVE_CALL",
            "error_type": "RuntimeError",
        },
        {
            "event_type": "OBSERVER_ERROR",
            "target": "Native.method",
            "phase": "AFTER_NATIVE_RETURN",
            "error_type": "RuntimeError",
        },
    ]
    assert hook_set.observer_error_count == 2


@pytest.mark.parametrize("value", [None, "", "1", "false"])
def test_runner_rejects_unapproved_engine_core_topology(value: str | None) -> None:
    environment = {} if value is None else {"VLLM_ENABLE_V1_MULTIPROCESSING": value}

    with pytest.raises(RunnerError, match="VLLM_ENABLE_V1_MULTIPROCESSING=0"):
        require_observation_topology(environment)


def test_runner_records_in_process_observation_topology() -> None:
    assert require_observation_topology({"VLLM_ENABLE_V1_MULTIPROCESSING": "0"}) == {
        "vllm_enable_v1_multiprocessing": False,
        "engine_core_observation_topology": "in_process",
    }


def scenario_config() -> ScenarioConfig:
    return ScenarioConfig(
        model="Qwen/Qwen2.5-0.5B-Instruct",
        model_revision="1" * 40,
        tokenizer="Qwen/Qwen2.5-0.5B-Instruct",
        tokenizer_revision="2" * 40,
        block_size=16,
        pressure_request_count=8,
        pressure_prompt_tokens=128,
        max_tokens=4,
        seed=7,
        temperature=0.0,
    )


def test_scenario_registry_exposes_exact_frozen_names() -> None:
    assert SCENARIO_NAMES == (
        "environment_smoke",
        "request_lifecycle_cleanup",
        "same_prefix_cross_request_reuse",
        "namespace_isolation",
        "block_eviction_and_reassignment",
        "partial_prefix",
    )


@pytest.mark.parametrize("scenario_name", SCENARIO_NAMES)
def test_each_scenario_has_explicit_program_ids_and_deterministic_sampling(
    scenario_name: str,
) -> None:
    plan = build_scenario(scenario_name, scenario_config())

    assert plan.name == scenario_name
    assert plan.requests
    assert all(request.program_id.strip() for request in plan.requests)
    assert len({request.program_id for request in plan.requests}) == len(plan.requests)
    assert plan.sampling.seed == 7
    assert plan.sampling.temperature == 0.0
    assert plan.sampling.max_tokens == 4


def test_namespace_scenario_varies_only_cache_salt() -> None:
    plan = build_scenario("namespace_isolation", scenario_config())

    assert len(plan.requests) == 2
    first, second = plan.requests
    assert first.prompt == second.prompt
    assert first.cache_salt != second.cache_salt


def test_partial_prefix_scenario_materializes_aligned_and_unaligned_token_pairs() -> None:
    plan = build_scenario("partial_prefix", scenario_config())

    class Tokenizer:
        def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
            assert add_special_tokens is False
            if text.startswith("suffix-"):
                return [9000 + ord(text[-1])]
            return list(range(256))

    prompts = materialize_prompts(plan, Tokenizer())
    token_ids = [prompt["prompt_token_ids"] for prompt in prompts]

    assert len(token_ids) == 4
    assert token_ids[0][:32] == token_ids[1][:32]
    assert token_ids[0][32:] != token_ids[1][32:]
    assert token_ids[2][:33] == token_ids[3][:33]
    assert token_ids[2][33:] != token_ids[3][33:]


def test_evidence_writer_uses_launcher_owned_directory_and_files(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run-1"
    run_directory.mkdir()
    run_directory.joinpath("commands.txt").write_text("env python runner.py\n")
    run_directory.joinpath("stderr.log").touch()

    writer = EvidenceWriter.create(run_directory)
    writer.write_environment({"z": 1, "a": 2})
    writer.append_observation({"z": 1, "a": 2})
    writer.write_summary({"z": 1, "a": 2})

    assert tuple(sorted(path.name for path in writer.run_directory.iterdir())) == tuple(
        sorted(REQUIRED_OUTPUT_FILENAMES)
    )
    assert json.loads(writer.environment_path.read_text()) == {"a": 2, "z": 1}
    assert writer.environment_path.read_text() == '{"a":2,"z":1}\n'
    assert writer.observations_path.read_text() == '{"a":2,"z":1}\n'
    assert writer.commands_path.read_text() == "env python runner.py\n"


def test_observer_errors_make_evidence_invalid() -> None:
    assert runner_module.evidence_status(0) == "SUCCESS"
    assert runner_module.evidence_status(1) == "INVALID"


def test_vllm_hook_bindings_are_exactly_the_four_audited_boundaries() -> None:
    class Scheduler:
        def schedule(self) -> None:
            return None

        def _free_request(self) -> None:
            return None

        def _free_blocks(self) -> None:
            return None

    class BlockPool:
        def get_new_blocks(self) -> None:
            return None

    bindings = build_vllm_hook_bindings(Scheduler, BlockPool)

    assert tuple(
        (binding.target, binding.before, binding.after) for binding in bindings
    ) == (
        ("Scheduler.schedule", False, True),
        ("Scheduler._free_request", True, False),
        ("Scheduler._free_blocks", False, True),
        ("BlockPool.get_new_blocks", True, True),
    )


def test_program_registry_uses_enqueue_returned_ids_without_inference() -> None:
    registry = ProgramRequestRegistry()
    registry.register_batch(
        ("external-program-a", "external-program-b"),
        ("native-request-41", "native-request-99"),
    )

    assert registry.program_for("native-request-41") == ProgramIdentity(
        "external-program-a"
    )
    assert registry.request_identity("native-request-99") == RequestIdentity(
        "native-request-99"
    )
    assert registry.program_for("unknown-native-id") is None


def test_program_registry_rejects_ambiguous_or_mismatched_registration() -> None:
    registry = ProgramRequestRegistry()

    with pytest.raises(ValueError, match="same length"):
        registry.register_batch(("program-a",), ("request-a", "request-b"))

    registry.register_batch(("program-a",), ("request-a",))
    with pytest.raises(ValueError, match="already registered"):
        registry.register_batch(("program-b",), ("request-a",))


def runner_cli_args(tmp_path: Path) -> list[str]:
    source_checkout = tmp_path / "vllm-metal-source"
    source_checkout.mkdir(exist_ok=True)
    return [
        "--scenario",
        "environment_smoke",
        "--run-id",
        "run-1",
        "--model",
        "Qwen/Qwen2.5-0.5B-Instruct",
        "--model-revision",
        "1" * 40,
        "--tokenizer",
        "Qwen/Qwen2.5-0.5B-Instruct",
        "--tokenizer-revision",
        "2" * 40,
        "--output-dir",
        str(tmp_path),
        "--observer-mode",
        "on",
        "--gpu-memory-utilization",
        "0.30",
        "--vllm-metal-source-checkout",
        str(source_checkout),
    ]


def test_runner_cli_and_llm_kwargs_pin_revisions_and_apc(tmp_path: Path) -> None:
    arguments = parse_args(runner_cli_args(tmp_path))

    assert build_llm_kwargs(arguments) == {
        "model": "Qwen/Qwen2.5-0.5B-Instruct",
        "revision": "1" * 40,
        "tokenizer": "Qwen/Qwen2.5-0.5B-Instruct",
        "tokenizer_revision": "2" * 40,
        "enable_prefix_caching": True,
        "gpu_memory_utilization": 0.30,
        "seed": 0,
    }


@pytest.mark.parametrize("option", ["--model-revision", "--tokenizer-revision"])
def test_runner_cli_rejects_mutable_hugging_face_revision(
    tmp_path: Path,
    option: str,
) -> None:
    args = runner_cli_args(tmp_path)
    args[args.index(option) + 1] = "main"

    with pytest.raises(SystemExit):
        parse_args(args)


def test_source_identity_requires_frozen_clean_contained_checkout(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "checkout"
    module_file = checkout / "vllm_metal/__init__.py"
    module_file.parent.mkdir(parents=True)
    module_file.touch()

    assert runner_module.validate_vllm_metal_source_identity(
        source_checkout=checkout,
        imported_module_file=module_file,
        git_head="a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb",
        working_tree_clean=True,
    ) == {
        "vllm_metal_imported_module_realpath": str(module_file.resolve()),
        "vllm_metal_source_checkout_realpath": str(checkout.resolve()),
        "vllm_metal_source_commit": "a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb",
        "vllm_metal_source_worktree_clean": True,
    }


@pytest.mark.parametrize(
    ("git_head", "working_tree_clean"),
    [
        ("b" * 40, True),
        ("a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb", False),
    ],
)
def test_source_identity_rejects_wrong_or_dirty_checkout(
    tmp_path: Path,
    git_head: str,
    working_tree_clean: bool,
) -> None:
    checkout = tmp_path / "checkout"
    module_file = checkout / "vllm_metal/__init__.py"
    module_file.parent.mkdir(parents=True)
    module_file.touch()

    with pytest.raises(RunnerError):
        runner_module.validate_vllm_metal_source_identity(
            source_checkout=checkout,
            imported_module_file=module_file,
            git_head=git_head,
            working_tree_clean=working_tree_clean,
        )


def test_source_identity_rejects_import_outside_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    module_file = tmp_path / "different/vllm_metal/__init__.py"
    module_file.parent.mkdir(parents=True)
    module_file.touch()

    with pytest.raises(RunnerError, match="inside source checkout"):
        runner_module.validate_vllm_metal_source_identity(
            source_checkout=checkout,
            imported_module_file=module_file,
            git_head="a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb",
            working_tree_clean=True,
        )


def test_execute_plan_registers_external_program_before_engine_runs() -> None:
    plan = build_scenario("same_prefix_cross_request_reuse", scenario_config())
    registry = ProgramRequestRegistry()

    class FakeLLM:
        def __init__(self) -> None:
            self.next_id = 0
            self.pending_id: str | None = None
            self.prompts: list[dict[str, str]] = []
            self.request_states: dict[str, SimpleNamespace] = {}
            self.llm_engine = SimpleNamespace(
                output_processor=SimpleNamespace(request_states=self.request_states)
            )

        def enqueue(self, prompts, sampling_params, use_tqdm):
            assert use_tqdm is False
            assert sampling_params is sentinel_sampling
            assert len(prompts) == 1
            self.prompts.append(prompts[0])
            self.pending_id = f"native-{self.next_id}"
            self.request_states[self.pending_id] = SimpleNamespace(
                external_req_id=str(self.next_id)
            )
            self.next_id += 1
            return [self.pending_id]

        def wait_for_completion(self, *, use_tqdm):
            assert use_tqdm is False
            assert self.pending_id is not None
            assert registry.program_for(self.pending_id) is not None
            return [self.pending_id]

    sentinel_sampling = object()
    llm = FakeLLM()
    outputs = execute_plan(llm, plan, sentinel_sampling, registry)

    assert outputs == ("native-0", "native-1")
    assert registry.program_for("native-0") == ProgramIdentity("program-reuse-a")
    assert registry.program_for("native-1") == ProgramIdentity("program-reuse-b")
    assert all(prompt["prompt"] for prompt in llm.prompts)


def test_completed_output_maps_external_id_to_internal_request_id() -> None:
    plan = build_scenario("environment_smoke", scenario_config())
    registry = ProgramRequestRegistry()

    class FakeLLM:
        def __init__(self) -> None:
            self.request_states: dict[str, SimpleNamespace] = {}

            self.llm_engine = SimpleNamespace(
                output_processor=SimpleNamespace(request_states=self.request_states)
            )

        def enqueue(self, prompts, sampling_params, use_tqdm):
            assert use_tqdm is False
            assert sampling_params is sentinel_sampling
            assert len(prompts) == 1
            internal_id = "0-deadbeef"
            self.request_states[internal_id] = SimpleNamespace(external_req_id="0")
            return [internal_id]

        def wait_for_completion(self, *, use_tqdm):
            assert use_tqdm is False
            return [
                SimpleNamespace(
                    request_id="0",
                    outputs=[],
                    finished=True,
                )
            ]

    sentinel_sampling = object()
    llm = FakeLLM()
    outputs = execute_plan(llm, plan, sentinel_sampling, registry)

    record = runner_module._completed_output_record(outputs[0], registry)

    assert record["request_id"] == "0-deadbeef"
    assert record["external_request_id"] == "0"
    assert record["program_id"] == "program-smoke"


def test_native_recorder_copies_free_queue_without_retaining_native_objects() -> None:
    class Node:
        def __init__(self, block_id: int, *, is_null: bool = False) -> None:
            self.block_id = block_id
            self.ref_cnt = 0
            self.block_hash = None
            self.block_hash_num_tokens = None
            self.is_null = is_null
            self.next_free_block = None

    head = Node(100, is_null=True)
    block = Node(7)
    tail = Node(101, is_null=True)
    head.next_free_block = block
    block.next_free_block = tail

    class Queue:
        fake_free_list_head = head
        fake_free_list_tail = tail

    class Pool:
        free_block_queue = Queue()

    records: list[dict[str, object]] = []
    recorder = NativeObservationRecorder(ProgramRequestRegistry(), records.append)
    recorder(
        ObservationContext(
            target="BlockPool.get_new_blocks",
            phase=ObservationPhase.BEFORE_NATIVE_CALL,
            receiver=Pool(),
            args=(1,),
            kwargs={},
        )
    )

    assert records == [
        {
            "event_index": 0,
            "free_queue": {
                "availability": "AVAILABLE",
                "blocks": [
                    {
                        "block_id": 7,
                        "cache_group_id": None,
                        "hash_num_tokens": None,
                        "is_null": False,
                        "native_hash_hex": None,
                        "ref_count": 0,
                    }
                ],
                "reason": None,
            },
            "phase": "BEFORE_NATIVE_CALL",
            "target": "BlockPool.get_new_blocks",
        }
    ]
    assert "Node" not in repr(records)


def test_runtime_identity_accepts_pinned_metal_profile() -> None:
    assert verify_runtime_identity(
        vllm_distribution_version="0.27.1+cpu",
        vllm_module_version="0.27.1+cpu",
        vllm_metal_distribution_version="0.3.0",
        platform_plugin_class="vllm_metal.platform.MetalPlatform",
        metal_platform_available=True,
        mlx_metal_available=True,
        mlx_configured_device="gpu",
        metal_paged_kv_enabled=True,
    ) == {
        "metal_paged_kv_enabled": True,
        "mlx_configured_device": "gpu",
        "mlx_metal_available": True,
        "platform_plugin_class": "vllm_metal.platform.MetalPlatform",
        "platform_plugin_identity": "vllm-metal",
        "qualification_status": "PENDING_REVIEW",
        "vllm_distribution_version_raw": "0.27.1+cpu",
        "vllm_metal_distribution_version_raw": "0.3.0",
        "vllm_module_version_raw": "0.27.1+cpu",
        "vllm_release_version": "0.27.1",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("vllm_distribution_version", "0.27.10+cpu"),
        ("vllm_module_version", "0.27.0+cpu"),
        ("platform_plugin_class", "vllm.platforms.cpu.CpuPlatform"),
        ("metal_platform_available", False),
        ("mlx_metal_available", False),
        ("mlx_configured_device", "cpu"),
        ("metal_paged_kv_enabled", False),
    ],
)
def test_runtime_identity_rejects_unqualified_profiles(field: str, value: object) -> None:
    inputs: dict[str, object] = {
        "vllm_distribution_version": "0.27.1+cpu",
        "vllm_module_version": "0.27.1+cpu",
        "vllm_metal_distribution_version": "arbitrary-raw-version",
        "platform_plugin_class": "vllm_metal.platform.MetalPlatform",
        "metal_platform_available": True,
        "mlx_metal_available": True,
        "mlx_configured_device": "gpu",
        "metal_paged_kv_enabled": True,
    }
    inputs[field] = value

    with pytest.raises(RunnerError):
        verify_runtime_identity(**inputs)  # type: ignore[arg-type]
