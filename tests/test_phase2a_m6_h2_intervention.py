from types import SimpleNamespace

import pytest

from kvopt.runtime.vllm.h2_intervention import (
    NativeBlockPoolCapture,
    invalidate_prefix_positions,
)


class Pool:
    def __init__(self) -> None:
        self.blocks = [
            SimpleNamespace(block_hash=bytes([i]), ref_cnt=0, is_null=False) for i in range(4)
        ]
        self.evicted = []

    def _maybe_evict_cached_block(self, block):
        self.evicted.append(block.block_hash)
        block.block_hash = None
        return True


@pytest.mark.parametrize(("position", "expected"), [("leading", [0, 1]), ("trailing", [2, 3])])
def test_h2_native_invalidation_targets_exact_positions(position, expected) -> None:
    pool = Pool()
    result = invalidate_prefix_positions(
        pool, [0, 1, 2, 3], [bytes([i]) for i in range(4)], position=position, count=2
    )
    assert result["selected_block_ids"] == expected
    assert all(pool.blocks[i].block_hash is None for i in expected)
    assert all(pool.blocks[i].ref_cnt == 0 for i in range(4))


def test_h2_stale_or_owned_prefix_rejected_before_mutation() -> None:
    pool = Pool()
    pool.blocks[3].ref_cnt = 1
    with pytest.raises(ValueError, match="free non-null"):
        invalidate_prefix_positions(
            pool, [0, 1, 2, 3], [bytes([i]) for i in range(4)], position="leading", count=1
        )
    assert pool.evicted == []


def test_h2_capture_forwards_observation_and_keeps_single_pool() -> None:
    seen = []
    capture = NativeBlockPoolCapture(seen.append)
    pool = Pool()
    context = SimpleNamespace(target="BlockPool.get_new_blocks", receiver=pool)

    capture(context)

    assert capture.pool is pool
    assert seen == [context]
    with pytest.raises(RuntimeError, match="more than one"):
        capture(SimpleNamespace(target=context.target, receiver=Pool()))
