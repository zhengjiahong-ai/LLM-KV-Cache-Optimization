"""Single-shot native runner wiring for Phase 5E Part A.

The module constructs the pinned AsyncLLM path and binds the Adapter,
Scheduler, KVCacheManager, BlockPool, allocation watermark, pressure outcome
reader, controller, gates, and archive.  Importing it never starts a GPU run.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kvopt.continuum.clock import Clock

from .phase5_archive import (
    create_phase5_evidence_archive,
    validate_phase5_evidence_archive,
)
from .phase5_asyncllm_adapter import (
    PINNED_VLLM_VERSION,
    AsyncLLMNativeAdapter,
    AsyncLLMProtocol,
    PinnedNativeBlockPoolPressureExecutor,
    resolve_pinned_inprocess_native_core,
)
from .phase5_gpu_conformance import Phase5GPUConformancePlan
from .phase5_replay import canonical_sha256
from .phase5e_native_evidence_source import (
    RuntimeEventEvidenceSource,
    resolve_runtime_event_reader,
    resolve_runtime_installation_report,
    resolve_runtime_integration,
)
from .phase5e_native_runtime import (
    Phase5ERuntimeEventSource,
    install_phase5e_a3_runtime,
)
from .phase5e_part_a import PartARequestInput, execute_phase5e_part_a


class Phase5ENativeRunnerError(RuntimeError):
    """The immutable runner input or pinned Native runtime failed closed."""


class Phase5ENativeEvidenceSource(Protocol):
    """Existing runtime instrumentation consumed by the native runner."""

    def pressure_outcome(
        self, boundary_id: str, allocated_block_ids: tuple[int, ...]
    ) -> Mapping[str, object]: ...

    def candidate_exposure_report(self) -> Mapping[str, object]: ...

    def a3_retention_input_manifest(self) -> Mapping[str, object]: ...

    def raw_evidence(self) -> Sequence[Mapping[str, object]]: ...

    def runtime_installation_report(self) -> Mapping[str, object]: ...

    def runtime_integration(self) -> object: ...


def resolve_production_evidence_source(engine: object) -> RuntimeEventEvidenceSource:
    """Bind the runner only to an explicitly installed same-core event source."""

    return RuntimeEventEvidenceSource(
        run_id="P5E-A-01",
        event_reader=resolve_runtime_event_reader(engine),
        runtime_installation_report=resolve_runtime_installation_report(engine),
        runtime_integration=resolve_runtime_integration(engine),
    )


def install_production_a3_runtime(
    *,
    engine: object,
    integration_factory: Callable[[Phase5ERuntimeEventSource], object],
    clock: Clock,
) -> tuple[RuntimeEventEvidenceSource, Mapping[str, object]]:
    """Install the reviewed A3 integration before resolving live evidence.

    The factory receives the only append-only event source, forcing the A3
    integration and evaluator to share one evidence stream.  No fallback
    integration is constructed here.
    """

    if not callable(integration_factory):
        raise TypeError("integration_factory must be callable")
    resolved = resolve_pinned_inprocess_native_core(engine)
    source = Phase5ERuntimeEventSource()
    integration = integration_factory(source)
    report = install_phase5e_a3_runtime(
        engine_core=resolved.engine_core,
        scheduler=resolved.scheduler,
        kv_cache_manager=resolved.kv_cache_manager,
        block_pool=resolved.block_pool,
        integration=integration,
        clock=clock,
        event_source=source,
    )
    evidence = RuntimeEventEvidenceSource(
        run_id="P5E-A-01",
        event_reader=resolve_runtime_event_reader(engine),
        runtime_installation_report=report,
        runtime_integration=integration,
    )
    return evidence, report


@dataclass(frozen=True, slots=True)
class Phase5ENativeAuthorization:
    run_id: str
    git_sha: str
    execution_manifest_sha256: str
    authorization_sha256: str


def claim_native_execution_once(
    *, freeze_root: Path, authorization: Phase5ENativeAuthorization
) -> Path:
    """Atomically consume the reviewed single-run authorization.

    The claim lives beside the immutable freeze so changing an output directory
    cannot turn one authorization into another GPU attempt.
    """

    claim_path = freeze_root / ".p5e-a-01-execution-consumed.json"
    payload = {
        "schema_version": "phase5e.part_a_execution_consumption.v1",
        "run_id": authorization.run_id,
        "git_sha": authorization.git_sha,
        "execution_manifest_sha256": authorization.execution_manifest_sha256,
        "authorization_sha256": authorization.authorization_sha256,
        "automatic_retry_allowed": False,
    }
    descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        claim_path.unlink(missing_ok=True)
        raise
    return claim_path


def load_integration_factory(reference: str) -> Callable[[Phase5ERuntimeEventSource], object]:
    """Load an explicitly reviewed ``module:function`` production factory."""

    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise Phase5ENativeRunnerError(
            "integration factory must use the module:function form"
        )
    factory = getattr(importlib.import_module(module_name), attribute, None)
    if not callable(factory):
        raise Phase5ENativeRunnerError("integration factory is not callable")
    return factory


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_native_execution_authorization(
    *, freeze_root: Path, authorization_path: Path, repository: Path
) -> Phase5ENativeAuthorization:
    """Validate a future M1 execution record against the immutable freeze."""

    manifest_path = freeze_root / "execution-manifest.json"
    if not manifest_path.is_file() or not authorization_path.is_file():
        raise Phase5ENativeRunnerError("freeze or authorization record is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    if manifest.get("execution_authorized") is not False:
        raise Phase5ENativeRunnerError("review manifest authorization state changed")
    if authorization.get("schema_version") != ("phase5e.part_a_execution_authorization.v1"):
        raise Phase5ENativeRunnerError("unsupported Part A authorization schema")
    if authorization.get("execution_authorized") is not True:
        raise Phase5ENativeRunnerError("Part A GPU execution is not authorized")
    if authorization.get("single_execution_only") is not True:
        raise Phase5ENativeRunnerError("authorization is not single-execution")
    if authorization.get("automatic_retry_allowed") is not False:
        raise Phase5ENativeRunnerError("authorization permits an automatic retry")
    manifest_sha = _sha256(manifest_path)
    if authorization.get("execution_manifest_sha256") != manifest_sha:
        raise Phase5ENativeRunnerError("authorization does not bind the freeze manifest")
    run_id = str(manifest.get("run_id", ""))
    git_sha = str(manifest.get("git_sha", ""))
    if authorization.get("run_id") != run_id or authorization.get("git_sha") != git_sha:
        raise Phase5ENativeRunnerError("authorization run or code identity mismatch")
    current_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current_sha != git_sha:
        raise Phase5ENativeRunnerError("runtime HEAD differs from authorized HEAD")
    if subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip():
        raise Phase5ENativeRunnerError("GPU execution requires a clean worktree")
    input_hashes = manifest.get("input_sha256")
    if not isinstance(input_hashes, Mapping):
        raise Phase5ENativeRunnerError("freeze manifest input hashes are missing")
    for name, expected in input_hashes.items():
        path = freeze_root / str(name)
        if not path.is_file() or _sha256(path) != expected:
            raise Phase5ENativeRunnerError(f"freeze input hash mismatch: {name}")
    return Phase5ENativeAuthorization(
        run_id=run_id,
        git_sha=git_sha,
        execution_manifest_sha256=manifest_sha,
        authorization_sha256=_sha256(authorization_path),
    )


def create_pinned_asyncllm(plan: Phase5GPUConformancePlan) -> AsyncLLMProtocol:
    """Create the reviewed in-process vLLM 0.27.1 engine without running work."""

    if os.environ.get("VLLM_ENABLE_V1_MULTIPROCESSING") != "0":
        raise Phase5ENativeRunnerError(
            "VLLM_ENABLE_V1_MULTIPROCESSING=0 is required before engine creation"
        )
    import vllm  # type: ignore[import-not-found]
    from vllm.engine.arg_utils import AsyncEngineArgs  # type: ignore[import-not-found]
    from vllm.v1.engine.async_llm import AsyncLLM  # type: ignore[import-not-found]

    if vllm.__version__ != PINNED_VLLM_VERSION:
        raise Phase5ENativeRunnerError("pinned vLLM version mismatch")
    budget = plan.resource_budget
    engine_identity = {
        "max_num_seqs": budget.engine_max_num_seqs,
        "block_size": budget.block_size_tokens,
        "kv_pool_blocks": budget.kv_pool_blocks,
        "max_model_len": budget.maximum_context_tokens,
    }
    if canonical_sha256(engine_identity) != plan.engine_configuration_sha256:
        raise Phase5ENativeRunnerError("runtime Engine configuration differs from frozen identity")
    engine_args = AsyncEngineArgs(
        model=budget.model_id,
        tokenizer=budget.model_id,
        revision=plan.model_revision,
        tokenizer_revision=plan.tokenizer_revision,
        max_model_len=budget.maximum_context_tokens,
        max_num_seqs=budget.engine_max_num_seqs,
        block_size=budget.block_size_tokens,
        num_gpu_blocks_override=budget.kv_pool_blocks,
        enable_prefix_caching=True,
        disable_log_stats=False,
    )
    engine = AsyncLLM.from_engine_args(engine_args, start_engine_loop=True)
    if getattr(engine, "output_handler", None) is not None:
        engine.shutdown()
        raise Phase5ENativeRunnerError(
            "AsyncLLM output handler started before lifecycle proxy installation"
        )
    return engine


async def _shutdown_engine(engine: object, grace_seconds: int) -> dict[str, object]:
    shutdown = getattr(engine, "shutdown", None)
    if not callable(shutdown):
        raise Phase5ENativeRunnerError("AsyncLLM shutdown is not observable")
    try:
        shutdown(timeout=float(grace_seconds))
    except TypeError:
        shutdown()
    output_handler = getattr(engine, "output_handler", None)
    if isinstance(output_handler, asyncio.Task) and not output_handler.done():
        await asyncio.gather(output_handler, return_exceptions=True)
    done = output_handler is None or (hasattr(output_handler, "done") and output_handler.done())
    if not done:
        raise Phase5ENativeRunnerError("AsyncLLM output handler survived shutdown")
    return {
        "schema_version": "phase5e.engine_cleanup.v1",
        "status": "PASS",
        "output_handler_done": done,
    }


def _count_block_ids(value: object) -> int:
    if isinstance(value, bool):
        raise Phase5ENativeRunnerError("invalid boolean Native block identity")
    if isinstance(value, int):
        return 1
    if isinstance(value, (list, tuple)):
        return sum(_count_block_ids(row) for row in value)
    block_id = getattr(value, "block_id", None)
    if isinstance(block_id, int) and not isinstance(block_id, bool):
        return 1
    raise Phase5ENativeRunnerError("Native allocation watermark shape is unknown")


def build_allocation_watermark_reader(
    *, adapter: AsyncLLMNativeAdapter, kv_cache_manager: object
) -> Callable[[tuple[str, ...]], Mapping[str, int]]:
    """Read request BlockTables by their randomized internal Native IDs."""

    get_block_ids = getattr(kv_cache_manager, "get_block_ids", None)
    get_blocks = getattr(kv_cache_manager, "get_blocks", None)
    method = get_block_ids if callable(get_block_ids) else get_blocks
    if not callable(method):
        raise Phase5ENativeRunnerError("KVCacheManager allocation watermark is not observable")

    def read(logical_request_ids: tuple[str, ...]) -> Mapping[str, int]:
        result = {}
        for logical_id in logical_request_ids:
            internal_id = adapter.internal_request_id(logical_id)
            result[logical_id] = _count_block_ids(method(internal_id))
        return result

    return read


def validate_runtime_engine_identity(*, engine: object, plan: Phase5GPUConformancePlan) -> None:
    """Compare the live AsyncLLM configuration with the frozen engine geometry."""

    config = getattr(engine, "vllm_config", None)
    scheduler = getattr(config, "scheduler_config", None)
    model = getattr(config, "model_config", None)
    cache = getattr(config, "cache_config", None)
    observed = {
        "max_num_seqs": getattr(scheduler, "max_num_seqs", None),
        "max_model_len": getattr(model, "max_model_len", None),
        "block_size": getattr(cache, "block_size", None),
        "kv_pool_blocks": getattr(cache, "num_gpu_blocks_override", None),
    }
    expected = {
        "max_num_seqs": plan.resource_budget.engine_max_num_seqs,
        "max_model_len": plan.resource_budget.maximum_context_tokens,
        "block_size": plan.resource_budget.block_size_tokens,
        "kv_pool_blocks": plan.resource_budget.kv_pool_blocks,
    }
    if observed != expected or canonical_sha256(expected) != (plan.engine_configuration_sha256):
        raise Phase5ENativeRunnerError(
            f"live AsyncLLM configuration differs from freeze: {observed!r}"
        )


def wire_pinned_native_adapter(
    *,
    engine: AsyncLLMProtocol,
    plan: Phase5GPUConformancePlan,
    evidence_source: Phase5ENativeEvidenceSource,
    run_epoch_monotonic: float,
    clock: Callable[[], float] = time.monotonic,
) -> AsyncLLMNativeAdapter:
    """Bind Adapter, observer, Scheduler, BlockPool and evidence to one core."""

    adapter = AsyncLLMNativeAdapter(
        engine=engine,
        vllm_version=plan.vllm_version,
        run_epoch_monotonic=run_epoch_monotonic,
        clock=clock,
        native_request_identity_observer=evidence_source.runtime_integration(),
    )
    validate_runtime_engine_identity(engine=engine, plan=plan)
    resolved = resolve_pinned_inprocess_native_core(engine)
    initial_free = resolved.block_pool.get_num_free_blocks()
    if initial_free != plan.resource_budget.kv_pool_blocks:
        raise Phase5ENativeRunnerError(
            "initial Native BlockPool size differs from frozen 2,048 blocks"
        )
    pressure = PinnedNativeBlockPoolPressureExecutor(
        block_pool=resolved.block_pool,
        adapter_engine_core=resolved.engine_core,
        scheduler_engine_core=resolved.engine_core,
        kv_instrumentation_engine_core=resolved.engine_core,
        evidence_reader=evidence_source.pressure_outcome,
        allocation_watermark_reader=build_allocation_watermark_reader(
            adapter=adapter, kv_cache_manager=resolved.kv_cache_manager
        ),
        execution_context_observer=evidence_source.runtime_integration(),
        clock=clock,
    )
    adapter.bind_native_pressure_executor(pressure)
    return adapter


async def run_phase5e_native_pipeline(
    *,
    plan: Phase5GPUConformancePlan,
    authorization: Phase5ENativeAuthorization,
    explicit_inputs: Mapping[str, object],
    engine: AsyncLLMProtocol,
    evidence_source: Phase5ENativeEvidenceSource,
    output_root: Path,
    archive_path: Path,
    run_epoch_monotonic: float,
    clock: Callable[[], float] = time.monotonic,
    sampling_factory: Callable[[Mapping[str, object]], object] | None = None,
    adapter_factory: Callable[
        [AsyncLLMProtocol, Phase5GPUConformancePlan, Phase5ENativeEvidenceSource, float],
        object,
    ]
    | None = None,
) -> dict[str, object]:
    """Execute exactly one authorized Part A run and produce immutable evidence."""

    if output_root.exists() or archive_path.exists():
        raise FileExistsError("Part A output or archive already exists")
    if authorization.run_id != "P5E-A-01" or authorization.git_sha != plan.git_sha:
        raise Phase5ENativeRunnerError("authorization and plan identities differ")
    prompt_tokens = explicit_inputs.get("prompt_token_ids")
    if not isinstance(prompt_tokens, Mapping):
        raise Phase5ENativeRunnerError("explicit Prompt Token IDs are missing")
    if explicit_inputs.get("pressure_token_ids_sha256") != (
        plan.pressure.pressure_prompt_token_ids_sha256
    ):
        raise Phase5ENativeRunnerError("explicit pressure input differs from plan")
    if sampling_factory is None:
        try:
            from vllm.sampling_params import (  # type: ignore[import-not-found]
                SamplingParams,
            )

            sampling = SamplingParams(**dict(plan.sampling_parameters))
        except (ImportError, TypeError, ValueError) as error:
            raise Phase5ENativeRunnerError("frozen SamplingParams cannot be built") from error
    else:
        sampling = sampling_factory(plan.sampling_parameters)
    requests = {}
    for request_id in plan.frozen_native_enqueue_order:
        token_ids = prompt_tokens.get(request_id)
        if not isinstance(token_ids, list) or canonical_sha256(token_ids) != dict(
            plan.workload_seal["request_token_ids_sha256"]
        ).get(request_id):
            raise Phase5ENativeRunnerError("Prompt Token identity mismatch")
        requests[request_id] = PartARequestInput(
            logical_request_id=request_id,
            prompt={"prompt_token_ids": token_ids},
            sampling_params=sampling,
        )
    output_root.mkdir(parents=True)
    _write_json(
        output_root / "preflight.json",
        {
            "schema_version": "phase5e.native_preflight.v1",
            "run_id": authorization.run_id,
            "git_sha": authorization.git_sha,
            "execution_manifest_sha256": authorization.execution_manifest_sha256,
            "authorization_sha256": authorization.authorization_sha256,
            "plan_sha256": plan.sha256,
            "runtime_installation": dict(
                evidence_source.runtime_installation_report()
            ),
            "status": "PASS",
        },
    )
    if adapter_factory is None:
        adapter = wire_pinned_native_adapter(
            engine=engine,
            plan=plan,
            evidence_source=evidence_source,
            run_epoch_monotonic=run_epoch_monotonic,
            clock=clock,
        )
    else:
        adapter = adapter_factory(engine, plan, evidence_source, run_epoch_monotonic)
    try:
        result = await execute_phase5e_part_a(
            plan=plan,
            run_id=authorization.run_id,
            requests=requests,
            adapter=adapter,
            candidate_exposure_evaluator=evidence_source.candidate_exposure_report,
            retention_input_manifest_provider=(
                evidence_source.a3_retention_input_manifest
            ),
            run_epoch_monotonic=run_epoch_monotonic,
            monotonic=clock,
        )
    except BaseException as error:
        cleanup_errors = []
        try:
            await adapter.shutdown(
                require_native_confirmation=False,
                require_frontend_observability=False,
            )
        except (Exception, asyncio.CancelledError) as cleanup_error:  # noqa: BLE001
            cleanup_errors.append(repr(cleanup_error))
        try:
            cleanup = await _shutdown_engine(engine, plan.resource_budget.shutdown_grace_seconds)
        except (Exception, asyncio.CancelledError) as cleanup_error:  # noqa: BLE001
            cleanup_errors.append(repr(cleanup_error))
            cleanup = {
                "schema_version": "phase5e.engine_cleanup.v1",
                "status": "FAIL_CLOSED",
                "errors": cleanup_errors,
            }
        _write_json(output_root / "engine-cleanup.json", cleanup)
        _write_json(
            output_root / "native-evidence.json",
            list(evidence_source.raw_evidence()),
        )
        _write_json(
            output_root / "run.json",
            {
                "schema_version": "phase5e.native_run.v1",
                "run_id": authorization.run_id,
                "status": "FAIL_CLOSED",
                "failure_reason": repr(error),
                "cleanup_errors": cleanup_errors,
                "automatic_retry_allowed": False,
            },
        )
        create_phase5_evidence_archive(
            source_root=output_root,
            archive_path=archive_path,
            required_relative_paths=(
                "preflight.json",
                "native-evidence.json",
                "engine-cleanup.json",
                "run.json",
            ),
        )
        raise
    cleanup = await _shutdown_engine(engine, plan.resource_budget.shutdown_grace_seconds)
    _write_json(output_root / "controller-result.json", result.to_dict())
    _write_json(output_root / "native-evidence.json", list(evidence_source.raw_evidence()))
    _write_json(output_root / "engine-cleanup.json", cleanup)
    run = {
        "schema_version": "phase5e.native_run.v1",
        "run_id": authorization.run_id,
        "status": result.status,
        "gpu_conformance_claim": "PASS" if result.status == "PASS" else "FAIL_CLOSED",
        "automatic_retry_allowed": False,
    }
    _write_json(output_root / "run.json", run)
    archive = create_phase5_evidence_archive(
        source_root=output_root,
        archive_path=archive_path,
        required_relative_paths=(
            "preflight.json",
            "controller-result.json",
            "native-evidence.json",
            "engine-cleanup.json",
            "run.json",
        ),
    )
    validation = validate_phase5_evidence_archive(archive_path)
    if validation.get("status") != "PASS":
        raise Phase5ENativeRunnerError("Part A archive validation failed")
    return {
        "schema_version": "phase5e.native_pipeline_result.v1",
        "status": result.status,
        "run_id": authorization.run_id,
        "archive": archive,
        "archive_validation": validation,
        "g0_freeze": "PASS",
        "g8_archive": "PASS",
        "automatic_retry_allowed": False,
    }
