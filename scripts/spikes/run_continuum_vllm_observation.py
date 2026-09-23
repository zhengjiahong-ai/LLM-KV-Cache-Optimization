"""Version-pinned native Metal observation runner for the Continuum spike.

Importing this module does not import vLLM, install hooks, read environment
variables, or create output files. Runtime discovery happens only in ``main``.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from functools import wraps
from importlib.metadata import version as distribution_version
from pathlib import Path
from types import MappingProxyType
from typing import Any, Self

from packaging.version import InvalidVersion, Version

from kvopt.continuum import ProgramIdentity, RequestIdentity
from kvopt.runtime.vllm.continuum_observation import (
    FreeQueueSnapshot,
    NativeBlockSnapshot,
    RequestBlockSnapshot,
    snapshot_block,
    snapshot_free_queue,
    snapshot_request_blocks,
)
from scripts.spikes.continuum_vllm_scenarios import (
    SCENARIO_NAMES,
    ScenarioPlan,
    materialize_prompts,
)

_MISSING = object()
_EXPECTED_VLLM_RELEASE = (0, 27, 1)
_EXPECTED_METAL_PLATFORM_CLASS = "vllm_metal.platform.MetalPlatform"
_VLLM_METAL_TAG = "v0.3.0.dev20260816085229"
_VLLM_METAL_COMMIT = "a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb"

REQUIRED_OUTPUT_FILENAMES = (
    "environment.json",
    "commands.txt",
    "observations.jsonl",
    "summary.json",
    "stderr.log",
)


class RunnerError(RuntimeError):
    """A configuration or runtime identity failure that invalidates evidence."""


def _immutable_revision(value: str) -> str:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise argparse.ArgumentTypeError(
            "revision must be a lowercase 40-hex commit"
        )
    return value


class ProgramRequestRegistry:
    """Map explicit external program IDs to IDs returned by ``LLM.enqueue``."""

    def __init__(self) -> None:
        self._programs_by_internal_request: dict[str, ProgramIdentity] = {}
        self._internal_by_external_request: dict[str, str] = {}

    def register_batch(
        self,
        program_ids: Sequence[str],
        native_request_ids: Sequence[str],
    ) -> None:
        programs = tuple(program_ids)
        requests = tuple(native_request_ids)
        if len(programs) != len(requests):
            raise ValueError("program and native request IDs must have the same length")
        if not programs:
            raise ValueError("registration batch must not be empty")

        additions: dict[str, ProgramIdentity] = {}
        for program_id, request_id in zip(programs, requests, strict=True):
            program = ProgramIdentity(program_id)
            request = RequestIdentity(request_id)
            if (
                request.value in self._programs_by_internal_request
                or request.value in additions
            ):
                raise ValueError(f"native request ID already registered: {request.value}")
            additions[request.value] = program
        self._programs_by_internal_request.update(additions)

    def register_external_batch(
        self,
        internal_request_ids: Sequence[str],
        external_request_ids: Sequence[str],
    ) -> None:
        internals = tuple(internal_request_ids)
        externals = tuple(external_request_ids)
        if len(internals) != len(externals):
            raise ValueError("internal and external request IDs must have the same length")
        if not internals:
            raise ValueError("external registration batch must not be empty")

        additions: dict[str, str] = {}
        for internal_request_id, external_request_id in zip(
            internals, externals, strict=True
        ):
            internal = RequestIdentity(internal_request_id)
            external = RequestIdentity(external_request_id)
            if internal.value not in self._programs_by_internal_request:
                raise ValueError(
                    f"internal request ID is not registered: {internal.value}"
                )
            if (
                external.value in self._internal_by_external_request
                or external.value in additions
            ):
                raise ValueError(
                    f"external request ID already registered: {external.value}"
                )
            additions[external.value] = internal.value
        self._internal_by_external_request.update(additions)

    def program_for(self, native_request_id: str) -> ProgramIdentity | None:
        request = RequestIdentity(native_request_id)
        return self._programs_by_internal_request.get(request.value)

    def internal_for_external(self, external_request_id: str) -> str | None:
        external = RequestIdentity(external_request_id)
        return self._internal_by_external_request.get(external.value)

    def request_identity(self, native_request_id: str) -> RequestIdentity:
        return RequestIdentity(native_request_id)

    def registered_request_ids(self) -> tuple[str, ...]:
        return tuple(self._programs_by_internal_request)


def _external_request_ids_for_internal(
    llm: object,
    internal_request_ids: Sequence[str],
) -> tuple[str, ...]:
    """Read vLLM's external IDs from the output processor's native state."""

    try:
        request_states = llm.llm_engine.output_processor.request_states  # type: ignore[attr-defined]
    except AttributeError as error:
        raise RunnerError(
            "vLLM output processor request states are unavailable"
        ) from error
    if not isinstance(request_states, Mapping):
        raise RunnerError("vLLM output processor request states are not a mapping")

    external_ids: list[str] = []
    for internal_request_id in internal_request_ids:
        internal = RequestIdentity(internal_request_id)
        state = request_states.get(internal.value)
        if state is None:
            raise RunnerError(
                f"vLLM request state is unavailable: {internal.value}"
            )
        external_request_id = getattr(state, "external_req_id", _MISSING)
        if not isinstance(external_request_id, str) or not external_request_id:
            raise RunnerError(
                f"vLLM external request ID is unavailable: {internal.value}"
            )
        external_ids.append(external_request_id)
    return tuple(external_ids)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the explicit inputs required for one formal observation run."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIO_NAMES, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-revision", type=_immutable_revision, required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--tokenizer-revision", type=_immutable_revision, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--observer-mode", choices=("off", "on"), required=True)
    parser.add_argument("--gpu-memory-utilization", type=float, required=True)
    parser.add_argument("--vllm-metal-source-checkout", type=Path, required=True)
    parser.add_argument("--pressure-request-count", type=int, default=32)
    parser.add_argument("--pressure-prompt-tokens", type=int, default=256)
    parser.add_argument("--max-tokens", type=int, default=8)
    return parser.parse_args(argv)


def build_llm_kwargs(arguments: argparse.Namespace) -> dict[str, object]:
    """Translate frozen CLI inputs into the exact vLLM constructor contract."""

    return {
        "model": arguments.model,
        "revision": arguments.model_revision,
        "tokenizer": arguments.tokenizer,
        "tokenizer_revision": arguments.tokenizer_revision,
        "enable_prefix_caching": True,
        "gpu_memory_utilization": arguments.gpu_memory_utilization,
        "seed": 0,
    }


def execute_plan(
    llm: object,
    plan: ScenarioPlan,
    sampling_params: object,
    registry: ProgramRequestRegistry,
    *,
    tokenizer: object | None = None,
) -> tuple[object, ...]:
    """Enqueue one request at a time and bind its explicit program ID."""

    outputs: list[object] = []
    prompts = materialize_prompts(plan, tokenizer)
    for request, prompt in zip(plan.requests, prompts, strict=True):
        native_request_ids = llm.enqueue(  # type: ignore[attr-defined]
            [prompt],
            sampling_params,
            use_tqdm=False,
        )
        internal_request_ids = tuple(native_request_ids)
        registry.register_batch((request.program_id,), internal_request_ids)
        registry.register_external_batch(
            internal_request_ids,
            _external_request_ids_for_internal(llm, internal_request_ids),
        )
        outputs.extend(llm.wait_for_completion(use_tqdm=False))  # type: ignore[attr-defined]
    return tuple(outputs)


def _json_line(value: Mapping[str, object]) -> str:
    return json.dumps(
        dict(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


@dataclass(frozen=True, slots=True)
class EvidenceWriter:
    """Write structured evidence into a launcher-prepared run directory."""

    run_directory: Path
    environment_path: Path
    commands_path: Path
    observations_path: Path
    summary_path: Path
    stderr_path: Path

    @classmethod
    def create(cls, run_directory: Path) -> EvidenceWriter:
        if not isinstance(run_directory, Path):
            raise TypeError("run_directory must be Path")
        if not run_directory.is_dir() or run_directory.is_symlink():
            raise RunnerError("launcher-owned run directory is unavailable")
        paths = {name: run_directory / name for name in REQUIRED_OUTPUT_FILENAMES}
        launcher_paths = {paths["commands.txt"], paths["stderr.log"]}
        if set(run_directory.iterdir()) != launcher_paths or any(
            path.is_symlink() or not path.is_file() for path in launcher_paths
        ):
            raise RunnerError("launcher-owned evidence files are invalid")
        for name in ("environment.json", "observations.jsonl", "summary.json"):
            path = paths[name]
            path.touch(exist_ok=False)
        return cls(
            run_directory=run_directory,
            environment_path=paths["environment.json"],
            commands_path=paths["commands.txt"],
            observations_path=paths["observations.jsonl"],
            summary_path=paths["summary.json"],
            stderr_path=paths["stderr.log"],
        )

    def write_environment(self, value: Mapping[str, object]) -> None:
        self.environment_path.write_text(_json_line(value), encoding="utf-8")

    def append_observation(self, value: Mapping[str, object]) -> None:
        with self.observations_path.open("a", encoding="utf-8") as stream:
            stream.write(_json_line(value))

    def write_summary(self, value: Mapping[str, object]) -> None:
        self.summary_path.write_text(_json_line(value), encoding="utf-8")


def require_observation_topology(environment: Mapping[str, str]) -> dict[str, object]:
    """Require the in-process EngineCore topology before importing vLLM."""

    if environment.get("VLLM_ENABLE_V1_MULTIPROCESSING") != "0":
        raise RunnerError(
            "formal observation requires VLLM_ENABLE_V1_MULTIPROCESSING=0"
        )
    return {
        "vllm_enable_v1_multiprocessing": False,
        "engine_core_observation_topology": "in_process",
    }


def verify_runtime_identity(
    *,
    vllm_distribution_version: str,
    vllm_module_version: str,
    vllm_metal_distribution_version: str,
    platform_plugin_class: str,
    metal_platform_available: bool,
    mlx_metal_available: bool,
    mlx_configured_device: str,
    metal_paged_kv_enabled: bool,
) -> dict[str, object]:
    """Validate the source-pinned Metal candidate without approving evidence."""

    try:
        distribution_release = Version(vllm_distribution_version).release
        module_release = Version(vllm_module_version).release
    except InvalidVersion as error:
        raise RunnerError("vLLM version is not valid PEP 440") from error
    if (
        distribution_release != _EXPECTED_VLLM_RELEASE
        or module_release != _EXPECTED_VLLM_RELEASE
    ):
        raise RunnerError("the candidate requires vLLM release 0.27.1")
    if platform_plugin_class != _EXPECTED_METAL_PLATFORM_CLASS:
        raise RunnerError("the pinned vLLM-Metal platform plugin is not active")
    if metal_platform_available is not True or mlx_metal_available is not True:
        raise RunnerError("MLX Metal GPU execution is unavailable")
    if mlx_configured_device != "gpu":
        raise RunnerError("vLLM-Metal must be configured for the MLX GPU")
    if metal_paged_kv_enabled is not True:
        raise RunnerError("vLLM-Metal paged KV must be enabled")
    return {
        "metal_paged_kv_enabled": True,
        "mlx_configured_device": "gpu",
        "mlx_metal_available": True,
        "platform_plugin_class": platform_plugin_class,
        "platform_plugin_identity": "vllm-metal",
        "qualification_status": "PENDING_REVIEW",
        "vllm_distribution_version_raw": vllm_distribution_version,
        "vllm_metal_distribution_version_raw": vllm_metal_distribution_version,
        "vllm_module_version_raw": vllm_module_version,
        "vllm_release_version": "0.27.1",
    }


def validate_vllm_metal_source_identity(
    *,
    source_checkout: Path,
    imported_module_file: Path,
    git_head: str,
    working_tree_clean: bool,
) -> dict[str, object]:
    """Validate that the imported editable source is the frozen clean checkout."""

    try:
        checkout_realpath = source_checkout.resolve(strict=True)
        module_realpath = imported_module_file.resolve(strict=True)
    except OSError as error:
        raise RunnerError("vLLM-Metal source identity path is unavailable") from error
    if not checkout_realpath.is_dir():
        raise RunnerError("vLLM-Metal source checkout must be a directory")
    if not module_realpath.is_relative_to(checkout_realpath):
        raise RunnerError("imported vLLM-Metal module is not inside source checkout")
    if git_head != _VLLM_METAL_COMMIT:
        raise RunnerError("vLLM-Metal source checkout is not at the frozen commit")
    if working_tree_clean is not True:
        raise RunnerError("vLLM-Metal source checkout must be clean")
    return {
        "vllm_metal_imported_module_realpath": str(module_realpath),
        "vllm_metal_source_checkout_realpath": str(checkout_realpath),
        "vllm_metal_source_commit": git_head,
        "vllm_metal_source_worktree_clean": True,
    }


def inspect_vllm_metal_source_identity(
    source_checkout: Path,
    imported_module_file: Path,
) -> dict[str, object]:
    """Read Git state from the selected local source checkout without mutation."""

    git_environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        head_result = subprocess.run(
            ["git", "-C", str(source_checkout), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            env=git_environment,
        )
        status_result = subprocess.run(
            [
                "git",
                "-C",
                str(source_checkout),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=git_environment,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RunnerError("vLLM-Metal source Git identity is unavailable") from error
    return validate_vllm_metal_source_identity(
        source_checkout=source_checkout,
        imported_module_file=imported_module_file,
        git_head=head_result.stdout.strip(),
        working_tree_clean=not status_result.stdout,
    )


def evidence_status(observer_error_count: int) -> str:
    if isinstance(observer_error_count, bool) or not isinstance(observer_error_count, int):
        raise TypeError("observer_error_count must be int")
    if observer_error_count < 0:
        raise ValueError("observer_error_count must be non-negative")
    return "SUCCESS" if observer_error_count == 0 else "INVALID"


def _apple_chip() -> str:
    completed = subprocess.run(
        ["sysctl", "-n", "machdep.cpu.brand_string"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    if not value:
        raise RunnerError("Apple chip identity is unavailable")
    return value


class ObservationPhase(str, Enum):
    """Position of an observation relative to one native call."""

    BEFORE_NATIVE_CALL = "BEFORE_NATIVE_CALL"
    AFTER_NATIVE_RETURN = "AFTER_NATIVE_RETURN"
    AFTER_NATIVE_EXCEPTION = "AFTER_NATIVE_EXCEPTION"


@dataclass(frozen=True, slots=True)
class ObservationContext:
    """Ephemeral native call context used only during a synchronous callback."""

    target: str
    phase: ObservationPhase
    receiver: object | None
    args: tuple[object, ...]
    kwargs: Mapping[str, object]
    native_result: object = _MISSING
    native_exception: BaseException | object = _MISSING

    def __post_init__(self) -> None:
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("target must be a non-empty string")
        if not isinstance(self.phase, ObservationPhase):
            raise TypeError("phase must be ObservationPhase")
        if not isinstance(self.args, tuple):
            raise TypeError("args must be tuple")
        if not isinstance(self.kwargs, Mapping):
            raise TypeError("kwargs must be a mapping")
        object.__setattr__(self, "kwargs", MappingProxyType(dict(self.kwargs)))

        if self.phase is ObservationPhase.BEFORE_NATIVE_CALL:
            if self.native_result is not _MISSING or self.native_exception is not _MISSING:
                raise ValueError("before context cannot contain a result or exception")
        elif self.phase is ObservationPhase.AFTER_NATIVE_RETURN:
            if self.native_result is _MISSING or self.native_exception is not _MISSING:
                raise ValueError("after-return context requires only a result")
        elif self.native_exception is _MISSING or self.native_result is not _MISSING:
            raise ValueError("after-exception context requires only an exception")


@dataclass(frozen=True, slots=True)
class HookBinding:
    """One class method and the observation phases required around it."""

    owner: type[object]
    method_name: str
    target: str
    before: bool = False
    after: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.owner, type):
            raise TypeError("owner must be a class")
        for value, field_name in (
            (self.method_name, "method_name"),
            (self.target, "target"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if type(self.before) is not bool or type(self.after) is not bool:
            raise TypeError("before and after must be bool")
        if not self.before and not self.after:
            raise ValueError("hook binding must observe at least one phase")


def build_vllm_hook_bindings(
    scheduler_class: type[object],
    block_pool_class: type[object],
) -> tuple[HookBinding, ...]:
    """Return only the four exact vLLM 0.27.1 observation boundaries."""

    return (
        HookBinding(
            scheduler_class,
            "schedule",
            "Scheduler.schedule",
            after=True,
        ),
        HookBinding(
            scheduler_class,
            "_free_request",
            "Scheduler._free_request",
            before=True,
        ),
        HookBinding(
            scheduler_class,
            "_free_blocks",
            "Scheduler._free_blocks",
            after=True,
        ),
        HookBinding(
            block_pool_class,
            "get_new_blocks",
            "BlockPool.get_new_blocks",
            before=True,
            after=True,
        ),
    )


Observer = Callable[[ObservationContext], None]
ErrorSink = Callable[[dict[str, str]], None]


class ObservationHookSet:
    """Install and restore a fixed set of temporary transparent class hooks."""

    def __init__(
        self,
        bindings: Sequence[HookBinding],
        observer: Observer,
        *,
        enabled: bool,
        error_sink: ErrorSink | None = None,
    ) -> None:
        if not isinstance(bindings, Sequence):
            raise TypeError("bindings must be an ordered sequence")
        self._bindings = tuple(bindings)
        if not all(isinstance(binding, HookBinding) for binding in self._bindings):
            raise TypeError("bindings items must be HookBinding")
        if len({(binding.owner, binding.method_name) for binding in self._bindings}) != len(
            self._bindings
        ):
            raise ValueError("hook bindings must not target the same method twice")
        if not callable(observer):
            raise TypeError("observer must be callable")
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        if error_sink is not None and not callable(error_sink):
            raise TypeError("error_sink must be callable or None")
        self._observer = observer
        self._enabled = enabled
        self._error_sink = error_sink
        self._observer_error_count = 0
        self._installed: list[tuple[type[object], str, Any]] = []

    @property
    def observer_error_count(self) -> int:
        return self._observer_error_count

    def __enter__(self) -> Self:
        if not self._enabled:
            return self
        try:
            for binding in self._bindings:
                original = getattr(binding.owner, binding.method_name)
                wrapped = self._wrap(binding, original)
                setattr(binding.owner, binding.method_name, wrapped)
                self._installed.append((binding.owner, binding.method_name, original))
        except BaseException:
            self._restore()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self._restore()
        return False

    def _restore(self) -> None:
        for owner, method_name, original in reversed(self._installed):
            setattr(owner, method_name, original)
        self._installed.clear()

    def _observe(self, context: ObservationContext) -> None:
        try:
            self._observer(context)
        except Exception as error:  # noqa: BLE001 -- isolation is the contract.
            self._observer_error_count += 1
            if self._error_sink is None:
                return
            record = {
                "event_type": "OBSERVER_ERROR",
                "target": context.target,
                "phase": context.phase.value,
                "error_type": type(error).__name__,
            }
            try:
                self._error_sink(record)
            except Exception:  # noqa: BLE001 -- diagnostics cannot affect native code.
                return

    def _wrap(self, binding: HookBinding, original: Callable[..., Any]):
        @wraps(original)
        def wrapped(receiver: object, *args: object, **kwargs: object):
            if binding.before:
                self._observe(
                    ObservationContext(
                        target=binding.target,
                        phase=ObservationPhase.BEFORE_NATIVE_CALL,
                        receiver=receiver,
                        args=args,
                        kwargs=kwargs,
                    )
                )
            try:
                result = original(receiver, *args, **kwargs)
            except BaseException as error:
                if binding.after:
                    self._observe(
                        ObservationContext(
                            target=binding.target,
                            phase=ObservationPhase.AFTER_NATIVE_EXCEPTION,
                            receiver=receiver,
                            args=args,
                            kwargs=kwargs,
                            native_exception=error,
                        )
                    )
                raise
            if binding.after:
                self._observe(
                    ObservationContext(
                        target=binding.target,
                        phase=ObservationPhase.AFTER_NATIVE_RETURN,
                        receiver=receiver,
                        args=args,
                        kwargs=kwargs,
                        native_result=result,
                    )
                )
            return result

        return wrapped


def _block_record(block: NativeBlockSnapshot) -> dict[str, object]:
    return {
        "block_id": block.block_id,
        "cache_group_id": block.cache_group_id,
        "hash_num_tokens": block.hash_num_tokens,
        "is_null": block.is_null,
        "native_hash_hex": block.native_hash_hex,
        "ref_count": block.ref_count,
    }


def _free_queue_record(snapshot: FreeQueueSnapshot) -> dict[str, object]:
    return {
        "availability": snapshot.availability.value,
        "blocks": [_block_record(block) for block in snapshot.blocks],
        "reason": snapshot.reason,
    }


def _request_record(snapshot: RequestBlockSnapshot) -> dict[str, object]:
    return {
        "availability": snapshot.availability.value,
        "block_groups": [
            [_block_record(block) for block in group]
            for group in snapshot.block_groups
        ],
        "program_id": snapshot.program_id.value,
        "reason": snapshot.reason,
        "request_id": snapshot.request_id.value,
    }


class NativeObservationRecorder:
    """Synchronously copy audited native state into JSON-compatible records."""

    def __init__(
        self,
        registry: ProgramRequestRegistry,
        emit: Callable[[dict[str, object]], None],
    ) -> None:
        if not isinstance(registry, ProgramRequestRegistry):
            raise TypeError("registry must be ProgramRequestRegistry")
        if not callable(emit):
            raise TypeError("emit must be callable")
        self._registry = registry
        self._emit = emit
        self._event_index = 0

    def __call__(self, context: ObservationContext) -> None:
        record: dict[str, object] = {
            "event_index": self._event_index,
            "phase": context.phase.value,
            "target": context.target,
        }
        self._event_index += 1

        if context.target == "BlockPool.get_new_blocks":
            queue = context.receiver.free_block_queue  # type: ignore[union-attr]
            record["free_queue"] = _free_queue_record(snapshot_free_queue(queue))
            if context.phase is ObservationPhase.AFTER_NATIVE_RETURN:
                record["allocated_blocks"] = [
                    _block_record(snapshot_block(block))
                    for block in context.native_result  # type: ignore[union-attr]
                ]
        elif context.target.startswith("Scheduler."):
            manager = context.receiver.kv_cache_manager  # type: ignore[union-attr]
            block_pool = manager.block_pool
            record["free_queue"] = _free_queue_record(
                snapshot_free_queue(block_pool.free_block_queue)
            )
            request_ids: tuple[str, ...]
            if context.target in {
                "Scheduler._free_request",
                "Scheduler._free_blocks",
            }:
                request_ids = (context.args[0].request_id,)  # type: ignore[attr-defined]
            else:
                native_requests = context.receiver.requests  # type: ignore[union-attr]
                request_ids = tuple(native_requests)

            request_records: list[dict[str, object]] = []
            unmapped_request_ids: list[str] = []
            for request_id in request_ids:
                program_id = self._registry.program_for(request_id)
                if program_id is None:
                    unmapped_request_ids.append(request_id)
                    continue
                request_records.append(
                    _request_record(
                        snapshot_request_blocks(
                            manager,
                            request_id=RequestIdentity(request_id),
                            program_id=program_id,
                        )
                    )
                )
            record["request_blocks"] = request_records
            record["unmapped_request_ids"] = unmapped_request_ids

        self._emit(record)


def _completed_output_record(
    output: object,
    registry: ProgramRequestRegistry,
) -> dict[str, object]:
    external_request_id = output.request_id  # type: ignore[attr-defined]
    request_id = registry.internal_for_external(external_request_id)
    program_id = None if request_id is None else registry.program_for(request_id)
    if program_id is None:
        raise RunnerError(
            "completed external request is not registered: "
            f"{external_request_id}"
        )
    completions = output.outputs  # type: ignore[attr-defined]
    return {
        "finished": bool(output.finished),  # type: ignore[attr-defined]
        "output_token_ids": [
            list(completion.token_ids) for completion in completions
        ],
        "program_id": program_id.value,
        "request_id": request_id,
        "external_request_id": external_request_id,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicit scenario in the source-pinned Metal candidate."""

    arguments = parse_args(argv)
    topology = require_observation_topology(os.environ)
    if Path(arguments.run_id).name != arguments.run_id or arguments.run_id in {".", ".."}:
        raise RunnerError("run-id must be one safe path component")
    if not arguments.output_dir.is_dir():
        raise RunnerError("output-dir must already exist")

    # These imports intentionally occur only after the topology fail-fast gate.
    import mlx.core as mx
    import torch
    import vllm
    import vllm_metal
    from vllm import LLM, SamplingParams
    from vllm.platforms import current_platform
    from vllm.v1.core.block_pool import BlockPool
    from vllm.v1.core.sched.scheduler import Scheduler
    from vllm_metal import MetalPlatform, get_config

    metal_config = get_config()
    platform_plugin_class = (
        f"{type(current_platform).__module__}.{type(current_platform).__qualname__}"
    )
    runtime_identity = verify_runtime_identity(
        vllm_distribution_version=distribution_version("vllm"),
        vllm_module_version=vllm.__version__,
        vllm_metal_distribution_version=distribution_version("vllm-metal"),
        platform_plugin_class=platform_plugin_class,
        metal_platform_available=MetalPlatform.is_available(),
        mlx_metal_available=bool(mx.metal.is_available()),
        mlx_configured_device=metal_config.mlx_device,
        metal_paged_kv_enabled=metal_config.use_paged_attention,
    )
    if vllm_metal.__file__ is None:
        raise RunnerError("vLLM-Metal imported module path is unavailable")
    source_identity = inspect_vllm_metal_source_identity(
        arguments.vllm_metal_source_checkout,
        Path(vllm_metal.__file__),
    )
    task3_commit_sha = os.environ.get("KVOPT_TASK3_COMMIT_SHA")
    if (
        task3_commit_sha is None
        or len(task3_commit_sha) != 40
        or any(character not in "0123456789abcdef" for character in task3_commit_sha)
    ):
        raise RunnerError("launcher must provide a lowercase 40-hex Git commit")
    worktree_clean_value = os.environ.get("KVOPT_TASK3_WORKTREE_CLEAN")
    if worktree_clean_value not in {"true", "false"}:
        raise RunnerError("launcher must report whether the project worktree is clean")
    writer = EvidenceWriter.create(arguments.output_dir / arguments.run_id)

    llm = LLM(**build_llm_kwargs(arguments))
    cache_config = llm.llm_engine.vllm_config.cache_config
    if cache_config.enable_prefix_caching is not True:
        raise RunnerError("automatic prefix caching is not enabled")

    from scripts.spikes.continuum_vllm_scenarios import ScenarioConfig, build_scenario

    scenario_config = ScenarioConfig(
        model=arguments.model,
        model_revision=arguments.model_revision,
        tokenizer=arguments.tokenizer,
        tokenizer_revision=arguments.tokenizer_revision,
        block_size=cache_config.block_size,
        pressure_request_count=arguments.pressure_request_count,
        pressure_prompt_tokens=arguments.pressure_prompt_tokens,
        max_tokens=arguments.max_tokens,
        seed=0,
        temperature=0.0,
    )
    plan = build_scenario(arguments.scenario, scenario_config)
    sampling_params = SamplingParams(
        max_tokens=plan.sampling.max_tokens,
        seed=plan.sampling.seed,
        temperature=plan.sampling.temperature,
    )

    environment_record: dict[str, object] = {
        **runtime_identity,
        **source_identity,
        **topology,
        "apple_chip": _apple_chip(),
        "automatic_prefix_caching": True,
        "block_size": cache_config.block_size,
        "check_timestamp_utc": datetime.now(UTC).isoformat(),
        "gpu_memory_utilization": arguments.gpu_memory_utilization,
        "host_architecture": platform.machine(),
        "host_operating_system": platform.system(),
        "host_version": platform.mac_ver()[0],
        "kv_cache_capacity_and_configuration": {
            "block_size": cache_config.block_size,
            "cache_dtype": str(cache_config.cache_dtype),
            "kv_cache_memory_bytes": cache_config.kv_cache_memory_bytes,
            "num_gpu_blocks": cache_config.num_gpu_blocks,
        },
        "model": arguments.model,
        "model_revision": arguments.model_revision,
        "mlx_default_device_raw": str(mx.default_device()),
        "mlx_lm_version_or_revision": distribution_version("mlx-lm"),
        "mlx_version": distribution_version("mlx"),
        "observer_mode": arguments.observer_mode,
        "platform_device_type_raw": current_platform.device_type,
        "pytorch_version": torch.__version__,
        "python_version": sys.version.split()[0],
        "run_id": arguments.run_id,
        "scenario": arguments.scenario,
        "task3_commit_sha": task3_commit_sha,
        "task3_worktree_clean": worktree_clean_value == "true",
        "tokenizer": arguments.tokenizer,
        "tokenizer_revision": arguments.tokenizer_revision,
        "vllm_metal_candidate_source_commit": _VLLM_METAL_COMMIT,
        "vllm_metal_module_version_raw": vllm_metal.__version__,
        "vllm_metal_candidate_tag": _VLLM_METAL_TAG,
    }
    writer.write_environment(environment_record)

    registry = ProgramRequestRegistry()
    observed_targets: set[str] = set()

    def emit_observation(record: dict[str, object]) -> None:
        target = record.get("target")
        if isinstance(target, str):
            observed_targets.add(target)
        writer.append_observation(record)

    recorder = NativeObservationRecorder(registry, emit_observation)
    bindings = build_vllm_hook_bindings(Scheduler, BlockPool)
    hook_set = ObservationHookSet(
        bindings,
        recorder,
        enabled=arguments.observer_mode == "on",
        error_sink=writer.append_observation,
    )
    with hook_set:
        outputs = execute_plan(
            llm,
            plan,
            sampling_params,
            registry,
            tokenizer=llm.get_tokenizer(),
        )

    output_records = [_completed_output_record(output, registry) for output in outputs]
    observer_error_count = hook_set.observer_error_count
    summary: dict[str, object] = {
        "completed_request_count": len(output_records),
        "inference_requests_completed": bool(output_records),
        "observer_mode": arguments.observer_mode,
        "observer_error_count": observer_error_count,
        "observed_hook_targets": sorted(observed_targets),
        "outputs": output_records,
        "run_id": arguments.run_id,
        "scenario": arguments.scenario,
        "status": evidence_status(observer_error_count),
    }
    if observer_error_count:
        summary["invalid_reason"] = "OBSERVER_ERROR"
    writer.write_summary(summary)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunnerError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
