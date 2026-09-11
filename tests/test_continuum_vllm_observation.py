from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from dataclasses import FrozenInstanceError, dataclass

import pytest

from kvopt.continuum import ProgramIdentity, RequestIdentity
from kvopt.runtime.vllm.continuum_observation import (
    FreeQueueSnapshot,
    NativeBlockSnapshot,
    ObservationAvailability,
    RequestBlockSnapshot,
    encode_native_hash,
    snapshot_block,
    snapshot_free_queue,
    snapshot_request_blocks,
)


@dataclass
class FakeBlock:
    block_id: int
    ref_cnt: int = 0
    block_hash: object | None = None
    block_hash_num_tokens: int | None = None
    is_null: bool = False
    next_free_block: FakeBlock | None = None


@dataclass
class FakeKVCacheBlocks:
    blocks: tuple[list[FakeBlock], ...]


class FakeManager:
    def __init__(self, groups: tuple[list[FakeBlock], ...]) -> None:
        self.groups = groups
        self.calls: list[str] = []

    def get_blocks(self, request_id: str) -> FakeKVCacheBlocks:
        self.calls.append(request_id)
        return FakeKVCacheBlocks(self.groups)


def make_queue(*blocks: FakeBlock):
    head = FakeBlock(-1)
    tail = FakeBlock(-1)
    current = head
    for block in blocks:
        current.next_free_block = block
        current = block
    current.next_free_block = tail

    class Queue:
        fake_free_list_head = head
        fake_free_list_tail = tail

        def popleft_n(self, count: int):  # pragma: no cover - forbidden path
            raise AssertionError(f"popleft_n must not be called: {count}")

        def remove(self, block: object):  # pragma: no cover - forbidden path
            raise AssertionError(f"remove must not be called: {block!r}")

        def append(self, block: object):  # pragma: no cover - forbidden path
            raise AssertionError(f"append must not be called: {block!r}")

    return Queue()


def test_native_hash_bytes_are_lowercase_hex() -> None:
    assert encode_native_hash(b"\x00\xaf") == "00af"


@pytest.mark.parametrize("value", [object(), "hash", 7, bytearray(b"hash")])
def test_native_hash_rejects_unapproved_values(value: object) -> None:
    with pytest.raises(TypeError, match="native hash must be bytes"):
        encode_native_hash(value)


def test_snapshot_block_copies_only_stable_values() -> None:
    native = FakeBlock(
        block_id=7,
        ref_cnt=2,
        block_hash=b"\x01\xfe",
        block_hash_num_tokens=32,
    )

    snapshot = snapshot_block(native, cache_group_id=3)
    native.block_id = 99
    native.block_hash = b"changed"

    assert snapshot == NativeBlockSnapshot(
        block_id=7,
        ref_count=2,
        native_hash_hex="01fe",
        hash_num_tokens=32,
        cache_group_id=3,
        is_null=False,
    )
    with pytest.raises(FrozenInstanceError):
        snapshot.block_id = 8  # type: ignore[misc]


def test_snapshot_block_preserves_observed_absent_hash() -> None:
    snapshot = snapshot_block(FakeBlock(block_id=1, is_null=True))

    assert snapshot.native_hash_hex is None
    assert snapshot.hash_num_tokens is None
    assert snapshot.cache_group_id is None
    assert snapshot.is_null is True


@pytest.mark.parametrize("native_hash_hex", ["AF", "0xz1", "abc", ""])
def test_block_snapshot_rejects_noncanonical_hash_hex(native_hash_hex: str) -> None:
    with pytest.raises(ValueError, match="lowercase hexadecimal"):
        NativeBlockSnapshot(
            block_id=1,
            ref_count=0,
            native_hash_hex=native_hash_hex,
            hash_num_tokens=16,
            cache_group_id=0,
            is_null=False,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("block_id", True, TypeError),
        ("block_id", -1, ValueError),
        ("ref_cnt", True, TypeError),
        ("ref_cnt", -1, ValueError),
        ("block_hash_num_tokens", True, TypeError),
        ("block_hash_num_tokens", -1, ValueError),
        ("is_null", 1, TypeError),
    ],
)
def test_snapshot_block_rejects_invalid_native_values(
    field: str, value: object, error: type[Exception]
) -> None:
    native = FakeBlock(block_id=1, block_hash=b"hash", block_hash_num_tokens=16)
    setattr(native, field, value)

    with pytest.raises(error):
        snapshot_block(native)


def test_request_snapshot_preserves_group_and_block_order() -> None:
    manager = FakeManager(
        (
            [FakeBlock(9, block_hash=b"a"), FakeBlock(3, block_hash=b"b")],
            [FakeBlock(7, block_hash=b"c")],
        )
    )

    snapshot = snapshot_request_blocks(
        manager,
        request_id=RequestIdentity("request-1"),
        program_id=ProgramIdentity("program-1"),
    )

    assert snapshot.availability is ObservationAvailability.AVAILABLE
    assert snapshot.reason is None
    assert manager.calls == ["request-1"]
    assert tuple(
        tuple(block.block_id for block in group) for group in snapshot.block_groups
    ) == ((9, 3), (7,))
    assert tuple(
        tuple(block.cache_group_id for block in group) for group in snapshot.block_groups
    ) == ((0, 0), (1,))


def test_request_snapshot_rejects_duplicate_non_null_ids_within_one_group() -> None:
    manager = FakeManager(([FakeBlock(4), FakeBlock(4)],))

    with pytest.raises(ValueError, match="duplicate non-null block IDs in cache group 0"):
        snapshot_request_blocks(
            manager,
            request_id=RequestIdentity("request-1"),
            program_id=ProgramIdentity("program-1"),
        )


def test_request_snapshot_allows_repeated_shared_null_block_in_one_group() -> None:
    null_block = FakeBlock(0, is_null=True)
    manager = FakeManager(([null_block, null_block, null_block],))

    snapshot = snapshot_request_blocks(
        manager,
        request_id=RequestIdentity("request-1"),
        program_id=ProgramIdentity("program-1"),
    )

    assert tuple(block.block_id for block in snapshot.block_groups[0]) == (0, 0, 0)
    assert all(block.is_null for block in snapshot.block_groups[0])


def test_request_snapshot_allows_equal_numeric_ids_in_different_groups() -> None:
    manager = FakeManager(([FakeBlock(4)], [FakeBlock(4)]))

    snapshot = snapshot_request_blocks(
        manager,
        request_id=RequestIdentity("request-1"),
        program_id=ProgramIdentity("program-1"),
    )

    assert tuple(group[0].block_id for group in snapshot.block_groups) == (4, 4)


def test_missing_request_mapping_is_explicitly_unavailable() -> None:
    class MissingManager:
        pass

    snapshot = snapshot_request_blocks(
        MissingManager(),
        request_id=RequestIdentity("request-1"),
        program_id=ProgramIdentity("program-1"),
    )

    assert snapshot == RequestBlockSnapshot(
        program_id=ProgramIdentity("program-1"),
        request_id=RequestIdentity("request-1"),
        block_groups=(),
        availability=ObservationAvailability.UNAVAILABLE,
        reason="get_blocks is unavailable",
    )


def test_absent_request_mapping_is_explicitly_unavailable() -> None:
    class Manager:
        def get_blocks(self, request_id: str) -> None:
            raise KeyError(request_id)

    snapshot = snapshot_request_blocks(
        Manager(),
        request_id=RequestIdentity("request-1"),
        program_id=ProgramIdentity("program-1"),
    )

    assert snapshot.availability is ObservationAvailability.UNAVAILABLE
    assert snapshot.reason == "request block mapping is unavailable"


def test_unsupported_request_group_shape_is_explicitly_unavailable() -> None:
    manager = FakeManager(())
    manager.groups = {1}  # type: ignore[assignment]

    snapshot = snapshot_request_blocks(
        manager,
        request_id=RequestIdentity("request-1"),
        program_id=ProgramIdentity("program-1"),
    )

    assert snapshot.availability is ObservationAvailability.UNAVAILABLE
    assert snapshot.block_groups == ()
    assert snapshot.reason == "native block groups must be an ordered sequence"


def test_request_extractor_does_not_hide_programming_errors() -> None:
    error = RuntimeError("manager failed")

    class Manager:
        def get_blocks(self, request_id: str) -> None:
            raise error

    with pytest.raises(RuntimeError) as caught:
        snapshot_request_blocks(
            Manager(),
            request_id=RequestIdentity("request-1"),
            program_id=ProgramIdentity("program-1"),
        )

    assert caught.value is error


def test_free_queue_snapshot_preserves_complete_native_order() -> None:
    queue = make_queue(FakeBlock(9), FakeBlock(3), FakeBlock(7))

    snapshot = snapshot_free_queue(queue)

    assert snapshot.availability is ObservationAvailability.AVAILABLE
    assert tuple(block.block_id for block in snapshot.blocks) == (9, 3, 7)


def test_free_queue_snapshot_rejects_duplicate_ids_in_one_queue() -> None:
    queue = make_queue(FakeBlock(4), FakeBlock(4))

    with pytest.raises(ValueError, match="duplicate block IDs in free queue"):
        snapshot_free_queue(queue)


def test_missing_free_queue_shape_is_explicitly_unavailable() -> None:
    snapshot = snapshot_free_queue(object())

    assert snapshot == FreeQueueSnapshot(
        blocks=(),
        availability=ObservationAvailability.UNAVAILABLE,
        reason="free queue sentinels are unavailable",
    )


def test_cyclic_free_queue_is_explicitly_unavailable() -> None:
    block = FakeBlock(1)
    queue = make_queue(block)
    block.next_free_block = block

    snapshot = snapshot_free_queue(queue)

    assert snapshot.availability is ObservationAvailability.UNAVAILABLE
    assert snapshot.reason == "free queue contains a cycle"


def test_snapshot_contracts_validate_identity_and_availability_types() -> None:
    with pytest.raises(TypeError, match="program_id must be ProgramIdentity"):
        RequestBlockSnapshot(
            program_id=RequestIdentity("request-1"),  # type: ignore[arg-type]
            request_id=RequestIdentity("request-1"),
            block_groups=(),
            availability=ObservationAvailability.AVAILABLE,
        )
    with pytest.raises(TypeError, match="availability must be ObservationAvailability"):
        FreeQueueSnapshot(blocks=(), availability="AVAILABLE")  # type: ignore[arg-type]


def test_unavailable_snapshot_requires_reason() -> None:
    with pytest.raises(ValueError, match="unavailable snapshot requires reason"):
        FreeQueueSnapshot(
            blocks=(),
            availability=ObservationAvailability.UNAVAILABLE,
        )


def test_import_has_no_vllm_logging_or_environment_side_effects() -> None:
    script = textwrap.dedent(
        """
        import contextlib
        import importlib
        import importlib.abc
        import io
        import json
        import logging
        import os
        import sys

        class RejectVLLMImport(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "vllm" or fullname.startswith("vllm."):
                    raise AssertionError(f"unexpected vLLM import: {fullname}")
                return None

        sys.meta_path.insert(0, RejectVLLMImport())
        environment_before = dict(os.environ)
        handlers_before = tuple(logging.getLogger().handlers)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            importlib.import_module("kvopt.runtime.vllm.continuum_observation")

        print(json.dumps({
            "environment_unchanged": dict(os.environ) == environment_before,
            "handlers_unchanged": tuple(logging.getLogger().handlers) == handlers_before,
            "stderr": stderr.getvalue(),
            "stdout": stdout.getvalue(),
            "vllm_loaded": any(
                name == "vllm" or name.startswith("vllm.") for name in sys.modules
            ),
        }, sort_keys=True))
        """
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in ("src", environment.get("PYTHONPATH")) if part
    )

    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        check=True,
        capture_output=True,
        cwd=os.getcwd(),
        env=environment,
        text=True,
    )

    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "environment_unchanged": True,
        "handlers_unchanged": True,
        "stderr": "",
        "stdout": "",
        "vllm_loaded": False,
    }
