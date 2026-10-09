"""Controlled native APC invalidation for isolated H2 mechanism probes."""

from collections.abc import Sequence
from typing import Any


class NativeBlockPoolCapture:
    """Capture the audited BlockPool receiver while forwarding observations."""

    def __init__(self, observer: Any) -> None:
        if not callable(observer):
            raise TypeError("observer must be callable")
        self._observer = observer
        self.pool: Any | None = None

    def __call__(self, context: Any) -> None:
        if context.target == "BlockPool.get_new_blocks":
            receiver = context.receiver
            if self.pool is not None and receiver is not self.pool:
                raise RuntimeError("H2 observed more than one native BlockPool")
            self.pool = receiver
        self._observer(context)


def invalidate_prefix_positions(
    pool: Any,
    ordered_block_ids: Sequence[int],
    ordered_cache_keys: Sequence[bytes],
    *,
    position: str,
    count: int,
) -> dict[str, object]:
    """Invalidate free native cache entries while preserving queue and ownership."""
    if position not in {"leading", "trailing"}:
        raise ValueError("H2 position must be leading or trailing")
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or not 0 <= count <= len(ordered_block_ids)
    ):
        raise ValueError("invalid H2 eviction count")
    if len(ordered_block_ids) != len(ordered_cache_keys):
        raise ValueError("H2 block and cache-key chains must align")
    if len(set(ordered_block_ids)) != len(ordered_block_ids):
        raise ValueError("H2 prefix must not contain duplicate blocks")
    blocks = []
    for block_id, expected_hash in zip(ordered_block_ids, ordered_cache_keys, strict=True):
        if isinstance(block_id, bool) or not isinstance(block_id, int):
            raise TypeError("H2 block ID must be an integer")
        if not 0 <= block_id < len(pool.blocks):
            raise ValueError("H2 block ID is out of range")
        if type(expected_hash) is not bytes:
            raise TypeError("H2 native cache key must be bytes")
        block = pool.blocks[block_id]
        if block.is_null or block.ref_cnt != 0:
            raise ValueError("H2 intervention requires free non-null prefix blocks")
        if block.block_hash != expected_hash:
            raise ValueError("H2 native cache identity changed before intervention")
        blocks.append(block)
    positions = (
        list(range(count))
        if position == "leading"
        else list(range(len(blocks) - count, len(blocks)))
    )
    before = [block.block_hash.hex() for block in blocks]
    for index in positions:
        if pool._maybe_evict_cached_block(blocks[index]) is not True:
            raise RuntimeError("native H2 cache invalidation did not evict the entry")
        if blocks[index].block_hash is not None:
            raise RuntimeError("native H2 cache identity survived invalidation")
    return {
        "mechanism": "native_apc_cache_entry_invalidation",
        "position": position,
        "count": count,
        "ordered_block_ids": list(ordered_block_ids),
        "selected_positions": positions,
        "selected_block_ids": [ordered_block_ids[index] for index in positions],
        "native_cache_keys_before": before,
        "native_cache_keys_after": [
            None if block.block_hash is None else block.block_hash.hex() for block in blocks
        ],
        "ownership_changed": False,
        "queue_reordered": False,
    }
