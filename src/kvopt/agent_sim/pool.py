"""Physical block pool with vLLM-0.27.1-style free queue semantics.

This is the CPU-only core of the Phase 2F simulator. It models:

* a fixed pool of physical block slots with content identity (chained hash);
* a free queue whose order *is* the native free-queue order (``lru_rank`` =
  position, 0 = head = first selected by native LRU);
* free-event bands: one request completion releases its whole block list;
  hashless blocks are prepended (queue head) and hashed blocks appended
  (queue tail), each group preserving list order (assumption A1, see
  ``docs/phase2f-m4-simulator-design.md`` §2);
* real physical eviction: a selected victim leaves the queue, its hash
  mapping is removed, and the slot is immediately reassigned to new content
  (``get_new_blocks`` -> ``_maybe_evict_cached_block`` semantics).

Physical block IDs are recycled slots, never content identity: the cache
mapping is the single source of truth for hits, so a recycled slot can never
produce a phantom hit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Block:
    """One physical block slot."""

    block_id: int
    content_id: str | None = None
    depth: int = 0
    ref_cnt: int = 0
    # Free-event band. One request completion produces *two* queue runs: the
    # hashless blocks are prepended (queue head) and the hashed blocks are
    # appended (queue tail), so a band is keyed by (event, kind). Blocks that
    # were never allocated are hashless and belong to the synthetic band
    # (-1, hashless), which sits between the freed hashless tails and the
    # hashed region of the queue.
    band_id: int = -1
    band_hashless: bool = True
    band_pos: int = -1
    has_block_hash: bool = False
    in_queue: bool = False
    prev: Block | None = None
    next: Block | None = None


class BlockPool:
    """Fixed-capacity physical block pool with an ordered free queue."""

    def __init__(self, total_blocks: int, *, free_order: str = "head_first") -> None:
        if isinstance(total_blocks, bool) or not isinstance(total_blocks, int):
            raise TypeError("total_blocks must be int")
        if total_blocks <= 0:
            raise ValueError("total_blocks must be positive")
        if free_order not in {"head_first", "tail_first"}:
            raise ValueError("free_order must be 'head_first' or 'tail_first'")
        self.total_blocks = total_blocks
        self.free_order = free_order
        self._head: Block | None = None
        self._tail: Block | None = None
        self._queue_size = 0
        self.free_event_counter = 0
        self.hashed_eviction_count = 0
        self.hashless_reuse_count = 0
        self.cache_mapping: dict[str, Block] = {}
        self.blocks = tuple(
            Block(block_id=index) for index in range(total_blocks)
        )
        for block in self.blocks:
            self._append(block)

    # ------------------------------------------------------------------
    # queue primitives (doubly linked list, mirroring FreeKVCacheBlockQueue)
    # ------------------------------------------------------------------
    def _unlink(self, block: Block) -> None:
        if not block.in_queue:
            raise ValueError("block is not in the free queue")
        if block.prev is not None:
            block.prev.next = block.next
        else:
            self._head = block.next
        if block.next is not None:
            block.next.prev = block.prev
        else:
            self._tail = block.prev
        block.prev = None
        block.next = None
        block.in_queue = False
        self._queue_size -= 1

    def _append(self, block: Block) -> None:
        if block.in_queue:
            raise ValueError("block is already in the free queue")
        block.prev = self._tail
        block.next = None
        if self._tail is not None:
            self._tail.next = block
        else:
            self._head = block
        self._tail = block
        block.in_queue = True
        self._queue_size += 1

    def _prepend(self, block: Block) -> None:
        if block.in_queue:
            raise ValueError("block is already in the free queue")
        block.next = self._head
        block.prev = None
        if self._head is not None:
            self._head.prev = block
        else:
            self._tail = block
        self._head = block
        block.in_queue = True
        self._queue_size += 1

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------
    @property
    def free_blocks(self) -> int:
        return self._queue_size

    def queue_blocks(self) -> tuple[Block, ...]:
        """Free queue in native order (index == lru_rank)."""
        blocks: list[Block] = []
        cursor = self._head
        while cursor is not None:
            blocks.append(cursor)
            cursor = cursor.next
        return tuple(blocks)

    def band_min_rank(self) -> dict[tuple[int, bool], int]:
        """Minimum lru_rank per (event, kind) band present in the queue."""
        minima: dict[tuple[int, bool], int] = {}
        for rank, block in enumerate(self.queue_blocks()):
            band = (block.band_id, block.band_hashless)
            current = minima.get(band)
            if current is None or rank < current:
                minima[band] = rank
        return minima

    def cached_content_blocks(self) -> int:
        return len(self.cache_mapping)

    # ------------------------------------------------------------------
    # acquire / release / evict
    # ------------------------------------------------------------------
    def acquire(self, content_id: str) -> Block | None:
        """Match one cached content block; returns None on miss."""
        block = self.cache_mapping.get(content_id)
        if block is None:
            return None
        if block.in_queue:
            self._unlink(block)
        block.ref_cnt += 1
        return block

    def release(self, blocks: tuple[Block, ...], *, event_id: int) -> None:
        """Release one request's block list (head-to-tail) to the free queue."""
        for block in blocks:
            if block.ref_cnt <= 0:
                raise ValueError("cannot release a block with ref_cnt 0")
            block.ref_cnt -= 1
        ordered = (
            list(blocks)
            if self.free_order == "head_first"
            else list(reversed(blocks))
        )
        self.free_event_counter += 1
        hashless_position = 0
        hashed_position = 0
        for block in ordered:
            if block.has_block_hash:
                hashed_position += 1
                block.band_id = event_id
                block.band_hashless = False
                block.band_pos = hashed_position
            else:
                hashless_position += 1
                block.band_id = event_id
                block.band_hashless = True
                block.band_pos = hashless_position
        # vLLM: hashless blocks are prepended (queue head), hashed appended.
        for block in ordered:
            if not block.has_block_hash:
                self._prepend(block)
        for block in ordered:
            if block.has_block_hash:
                self._append(block)

    def check_invariants(self) -> None:
        """Assert the physical-cache invariants (called once per run).

        1. every block is either queued (``in_queue``, ``ref_cnt == 0``) or
           owned (``ref_cnt >= 1``, not queued) — never both, never neither;
        2. the cache mapping is consistent: each mapped block's
           ``content_id`` equals its key;
        3. no content identity is mapped twice (no duplicate content);
        4. the queue size equals the number of queued blocks.
        """
        queued = 0
        owners: dict[str, int] = {}
        for block in self.blocks:
            if block.in_queue:
                if block.ref_cnt != 0:
                    raise AssertionError(
                        f"block {block.block_id} is queued with ref_cnt {block.ref_cnt}"
                    )
                queued += 1
            elif block.ref_cnt < 1:
                raise AssertionError(
                    f"block {block.block_id} is neither queued nor owned"
                )
            if block.has_block_hash:
                mapped = self.cache_mapping.get(block.content_id or "")
                if mapped is not block:
                    raise AssertionError(
                        f"block {block.block_id} holds content "
                        f"{block.content_id} but the mapping points elsewhere"
                    )
                owners[block.content_id or ""] = owners.get(block.content_id or "", 0) + 1
        for content_id, count in owners.items():
            if count > 1:
                raise AssertionError(
                    f"content {content_id} is held by {count} blocks"
                )
        if queued != self._queue_size:
            raise AssertionError("queue size does not match queued block count")

    def evict_and_take(self, block_id: int, content_id: str, depth: int, *, hashed: bool) -> Block:
        """Physically evict one queued victim and reassign the slot."""
        block = self.blocks[block_id]
        if not block.in_queue or block.ref_cnt != 0:
            raise ValueError("victim must be a free-queue block with ref_cnt 0")
        if hashed:
            existing = self.cache_mapping.get(content_id)
            if existing is not None and existing is not block:
                raise ValueError(
                    f"content {content_id} is already cached in block "
                    f"{existing.block_id}; duplicate content assignment"
                )
        self._unlink(block)
        if block.has_block_hash:
            mapped = self.cache_mapping.get(block.content_id or "")
            if mapped is block:
                del self.cache_mapping[block.content_id or ""]
            self.hashed_eviction_count += 1
        else:
            self.hashless_reuse_count += 1
        block.content_id = content_id
        block.depth = depth
        block.has_block_hash = hashed
        block.ref_cnt = 1
        block.band_id = -1
        block.band_hashless = not hashed
        block.band_pos = -1
        if hashed:
            self.cache_mapping[content_id] = block
        return block
