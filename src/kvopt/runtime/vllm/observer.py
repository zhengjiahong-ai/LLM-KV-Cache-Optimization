"""Opt-in policy adapter hook for a disposable vLLM container."""

from __future__ import annotations

import json
import os
from typing import Any

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


def install_from_environment() -> None:
    mode = os.getenv("KVOPT_POLICY_MODE")
    if mode:
        install_policy_observer(mode)

