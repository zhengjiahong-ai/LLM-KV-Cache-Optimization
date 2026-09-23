"""Opt-in policy adapter hook for a disposable vLLM container."""

from __future__ import annotations

import json
import math
import os
from collections import deque
from dataclasses import replace
from typing import Any

from kvopt.continuum import (
    BlockIdentity,
    Clock,
    RequestIdentity,
    RetentionMode,
    SchedulerMode,
)

from .adapter import NativeLRUAdapter
from .bridge import VLLMEvictionBridge


def _emit(event: str, **fields: Any) -> None:
    print("[KVOPT] " + json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def _queue_blocks(queue: Any) -> list[Any]:
    blocks: list[Any] = []
    current = queue.fake_free_list_head.next_free_block
    while current is not queue.fake_free_list_tail:
        blocks.append(current)
        current = current.next_free_block
    return blocks


def _read_clock_timestamp(clock: Clock) -> float:
    """Read and validate one timestamp at the hook consumer boundary."""
    value = clock.now()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("clock.now() must return a real number")
    try:
        timestamp = float(value)
    except OverflowError as error:
        raise ValueError("clock.now() must return a finite timestamp") from error
    if not math.isfinite(timestamp) or timestamp < 0.0:
        raise ValueError("clock.now() must return a finite non-negative timestamp")
    return timestamp


def install_policy_observer(mode: str) -> None:
    if mode not in {"shadow", "controlled"}:
        raise ValueError(f"unsupported observer mode: {mode}")
    from vllm.v1.core.block_pool import BlockPool
    from vllm.v1.core.kv_cache_utils import FreeKVCacheBlockQueue

    if getattr(FreeKVCacheBlockQueue, "_kvopt_policy_installed", False):
        return
    original = FreeKVCacheBlockQueue.popleft_n

    def observed_popleft_n(queue: Any, required_blocks: int) -> list[Any]:
        snapshot = _queue_blocks(queue)
        native = [block.block_id for block in snapshot[:required_blocks]]
        # NativeLRUAdapter needs queue order only; this queue deliberately
        # does not own the pool's complete collection of blocks.
        bridge = VLLMEvictionBridge(NativeLRUAdapter(), total_blocks=len(snapshot))
        adapter = bridge.select_blocks(snapshot, required_blocks, free_blocks=queue.num_free_blocks)
        _emit("POLICY_SHADOW", required_blocks=required_blocks, native=native, adapter=adapter, match=native == adapter)
        if mode == "shadow":
            return original(queue, required_blocks)
        by_id = {block.block_id: block for block in snapshot}
        selected = [by_id[block_id] for block_id in adapter]
        for block in selected:
            queue.remove(block)
        _emit("POLICY_CONTROLLED", required_blocks=required_blocks, selected=adapter)
        return selected

    original_evict = BlockPool._maybe_evict_cached_block

    def observed_evict(pool: Any, block: Any) -> Any:
        had_hash = block.block_hash is not None
        result = original_evict(pool, block)
        if had_hash:
            _emit("EVICT_CACHED", block_id=block.block_id, metadata_removed=block.block_hash is None)
        return result

    FreeKVCacheBlockQueue.popleft_n = observed_popleft_n
    BlockPool._maybe_evict_cached_block = observed_evict
    FreeKVCacheBlockQueue._kvopt_policy_installed = True


def install_retention_hook(
    *, mode: RetentionMode, integration: Any, clock: Clock
) -> None:
    """Install the narrow retention integration hook for one vLLM process.

    Native mode deliberately leaves the vLLM methods untouched.  Shadow mode
    plans from a complete queue snapshot and delegates removal to the native
    method.  Controlled mode maps the validated block IDs back to the exact
    snapshot objects before removing them through the existing queue method.
    """
    if not isinstance(mode, RetentionMode):
        raise TypeError("mode must be RetentionMode")
    if mode is RetentionMode.NATIVE:
        return
    if not isinstance(clock, Clock):
        raise TypeError("clock must implement Clock")
    if not callable(getattr(integration, "apply_pressure", None)):
        raise TypeError("integration must provide apply_pressure")
    if not callable(getattr(integration, "observe_native_eviction", None)):
        raise TypeError("integration must provide observe_native_eviction")

    from vllm.v1.core.block_pool import BlockPool
    from vllm.v1.core.kv_cache_utils import FreeKVCacheBlockQueue

    if getattr(FreeKVCacheBlockQueue, "_kvopt_policy_installed", False):
        return

    original_popleft = FreeKVCacheBlockQueue.popleft_n

    def retained_popleft(queue: Any, required_blocks: int) -> list[Any]:
        snapshot = tuple(_queue_blocks(queue))
        selected_objects: list[Any] = []
        by_id = {block.block_id: block for block in snapshot}

        def remove_selected(block_ids: tuple[int, ...]) -> None:
            normalized_ids = tuple(block_ids)
            mapped: list[Any] = []
            for block_id in normalized_ids:
                try:
                    mapped.append(by_id[block_id])
                except KeyError as error:
                    raise ValueError(f"unknown block ID: {block_id}") from error
            selected_objects.extend(mapped)
            for block in mapped:
                queue.remove(block)

        def reject_remove(_block_ids: tuple[int, ...]) -> None:
            raise RuntimeError("shadow retention integration attempted queue removal")

        callback = remove_selected if mode is RetentionMode.CONTROLLED else reject_remove
        integration.apply_pressure(
            mode=mode,
            blocks=snapshot,
            required_blocks=required_blocks,
            timestamp=_read_clock_timestamp(clock),
            remove_selected=callback,
        )
        if mode is RetentionMode.SHADOW:
            return original_popleft(queue, required_blocks)
        return selected_objects

    original_evict = BlockPool._maybe_evict_cached_block

    def retained_evict(pool: Any, block: Any) -> Any:
        result = original_evict(pool, block)
        if result is True:
            integration.observe_native_eviction(BlockIdentity(block.block_id))
        return result

    FreeKVCacheBlockQueue.popleft_n = retained_popleft
    BlockPool._maybe_evict_cached_block = retained_evict
    FreeKVCacheBlockQueue._kvopt_policy_installed = True


def install_scheduler_hook(*, mode: SchedulerMode, runtime: Any, policy: Any) -> None:
    """Install the narrow scheduler ordering hook for one vLLM process."""
    if not isinstance(mode, SchedulerMode):
        raise TypeError("mode must be SchedulerMode")
    if mode is SchedulerMode.NATIVE:
        return
    if not callable(getattr(runtime, "scheduler_candidates", None)):
        raise TypeError("runtime must provide scheduler_candidates")
    if not callable(getattr(policy, "order", None)):
        raise TypeError("policy must provide order")

    from vllm.v1.core.sched.scheduler import Scheduler
    from vllm.v1.request import RequestStatus

    if getattr(Scheduler, "_kvopt_scheduler_installed", False):
        return
    original_schedule = Scheduler.schedule

    def retained_schedule(scheduler: Any, *args: Any, **kwargs: Any) -> Any:
        if mode is SchedulerMode.CONTROLLED:
            if not isinstance(scheduler.waiting, deque):
                raise TypeError("controlled scheduler hook requires an FCFS deque")
            skipped_waiting = getattr(scheduler, "skipped_waiting", ())
            if tuple(skipped_waiting):
                raise ValueError(
                    "controlled scheduler hook requires an empty skipped_waiting queue"
                )
        waiting = tuple(scheduler.waiting)
        native_request_ids = tuple(request.request_id for request in waiting)
        runtime_request_ids = tuple(RequestIdentity(request_id) for request_id in native_request_ids)
        candidates = tuple(runtime.scheduler_candidates(runtime_request_ids))
        by_id = {candidate.request_id.value: candidate for candidate in candidates}
        mapped_candidates = tuple(
            replace(
                by_id[request.request_id],
                is_preempted_waiting=request.status is RequestStatus.PREEMPTED,
            )
            for request in waiting
        )
        ordered_ids = tuple(policy.order(mapped_candidates))
        if len(ordered_ids) != len(waiting) or len(set(ordered_ids)) != len(ordered_ids):
            raise ValueError("scheduler policy must return each waiting request exactly once")
        if not all(isinstance(request_id, RequestIdentity) for request_id in ordered_ids):
            raise TypeError("scheduler policy must return RequestIdentity values")
        expected_ids = set(native_request_ids)
        actual_ids = {request_id.value for request_id in ordered_ids}
        if actual_ids != expected_ids:
            raise ValueError("scheduler policy returned unknown request IDs")

        if mode is SchedulerMode.CONTROLLED:
            by_native_id = {request.request_id: request for request in waiting}
            reordered = [
                by_native_id[request_id.value]
                for request_id in ordered_ids
            ]
            scheduler.waiting.clear()
            scheduler.waiting.extend(reordered)
        return original_schedule(scheduler, *args, **kwargs)

    Scheduler.schedule = retained_schedule
    Scheduler._kvopt_scheduler_installed = True


def install_from_environment() -> None:
    mode = os.getenv("KVOPT_POLICY_MODE")
    if mode:
        install_policy_observer(mode)
