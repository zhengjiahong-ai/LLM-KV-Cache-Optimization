from dataclasses import dataclass

import pytest

from kvopt.runtime.vllm import NativeLRUAdapter, VLLMEvictionBridge


@dataclass
class FakeBlock:
    block_id: int
    ref_cnt: int = 0
    block_hash: object | None = object()


def test_native_lru_adapter_preserves_free_queue_order() -> None:
    bridge = VLLMEvictionBridge(policy=NativeLRUAdapter(), total_blocks=16)
    blocks = [FakeBlock(462), FakeBlock(461), FakeBlock(460), FakeBlock(459)]

    selected = bridge.select_blocks(blocks, required_blocks=3, timestamp=1.0)

    assert selected == [462, 461, 460]


def test_candidate_snapshot_records_native_state() -> None:
    bridge = VLLMEvictionBridge(policy=NativeLRUAdapter(), total_blocks=16)
    blocks = [FakeBlock(10, ref_cnt=0, block_hash="hash"), FakeBlock(11, block_hash=None)]

    candidates = bridge.build_candidates(blocks)

    assert candidates[0].block_id == 10
    assert candidates[0].lru_rank == 0
    assert candidates[0].has_block_hash is True
    assert candidates[1].lru_rank == 1
    assert candidates[1].has_block_hash is False


def test_bridge_rejects_too_few_victims() -> None:
    class BadPolicy(NativeLRUAdapter):
        def select_victims(self, candidates, context):
            return []

    bridge = VLLMEvictionBridge(policy=BadPolicy(), total_blocks=16)

    with pytest.raises(ValueError, match="too few"):
        bridge.select_blocks([FakeBlock(1), FakeBlock(2)], required_blocks=1)


def test_bridge_rejects_unknown_victim() -> None:
    class BadPolicy(NativeLRUAdapter):
        def select_victims(self, candidates, context):
            return [999]

    bridge = VLLMEvictionBridge(policy=BadPolicy(), total_blocks=16)

    with pytest.raises(ValueError, match="non-candidate"):
        bridge.select_blocks([FakeBlock(1)], required_blocks=1)
