"""Read-only vLLM-to-Continuum observation values and extractors.

The module deliberately imports no vLLM package and installs no hook. It copies
only the pinned observation surface into immutable project-owned values.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from kvopt.continuum import ProgramIdentity, RequestIdentity


class ObservationAvailability(str, Enum):
    """Whether a complete native snapshot was available at one boundary."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class _UnsupportedNativeShape(TypeError):
    """An expected native observation field is absent or has no stable shape."""


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def _require_optional_non_negative_int(value: object, field_name: str) -> None:
    if value is not None:
        _require_non_negative_int(value, field_name)


def _require_identity(value: object, expected: type[object], field_name: str) -> None:
    if not isinstance(value, expected):
        raise TypeError(f"{field_name} must be {expected.__name__}")


def _require_optional_reason(value: object) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError("reason must be str or None")
    if not value.strip():
        raise ValueError("reason must not be empty")


def _ordered_tuple(value: object, field_name: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an ordered sequence")
    return tuple(value)


def _native_ordered_tuple(value: object, field_name: str) -> tuple[object, ...]:
    try:
        return _ordered_tuple(value, field_name)
    except TypeError as error:
        raise _UnsupportedNativeShape(str(error)) from error


def _read_native_attribute(value: object, field_name: str) -> object:
    try:
        return getattr(value, field_name)
    except AttributeError as error:
        raise _UnsupportedNativeShape(
            f"native object must expose {field_name}"
        ) from error


def encode_native_hash(value: object) -> str:
    """Encode the exact native ``block_hash`` bytes without decomposition.

    In vLLM 0.27.1 this value may be ``BlockHashWithGroupId`` and therefore
    already contain a packed cache-group ID. It is not interpreted here as a
    pure content hash or used to construct ``PrefixIdentity``.
    """

    if type(value) is not bytes:
        raise TypeError("native hash must be bytes")
    return value.hex()


@dataclass(frozen=True, slots=True)
class NativeBlockSnapshot:
    """Immutable copy of one native KV-cache block observation.

    ``native_hash_hex`` is the exact encoded native ``block_hash`` value; its
    content/namespace components remain an evidence question for Commit 4.
    """

    block_id: int
    ref_count: int
    native_hash_hex: str | None
    hash_num_tokens: int | None
    cache_group_id: int | None
    is_null: bool

    def __post_init__(self) -> None:
        _require_non_negative_int(self.block_id, "block_id")
        _require_non_negative_int(self.ref_count, "ref_count")
        _require_optional_non_negative_int(self.hash_num_tokens, "hash_num_tokens")
        _require_optional_non_negative_int(self.cache_group_id, "cache_group_id")
        if self.native_hash_hex is not None:
            if not isinstance(self.native_hash_hex, str):
                raise TypeError("native_hash_hex must be str or None")
            if (
                not self.native_hash_hex
                or len(self.native_hash_hex) % 2 != 0
                or any(character not in "0123456789abcdef" for character in self.native_hash_hex)
            ):
                raise ValueError("native_hash_hex must be lowercase hexadecimal bytes")
        elif self.hash_num_tokens is not None:
            raise ValueError("hash_num_tokens requires native_hash_hex")
        if type(self.is_null) is not bool:
            raise TypeError("is_null must be bool")


@dataclass(frozen=True, slots=True)
class RequestBlockSnapshot:
    """Ordered per-cache-group block snapshot for one live request."""

    program_id: ProgramIdentity
    request_id: RequestIdentity
    block_groups: tuple[tuple[NativeBlockSnapshot, ...], ...]
    availability: ObservationAvailability
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_identity(self.program_id, ProgramIdentity, "program_id")
        _require_identity(self.request_id, RequestIdentity, "request_id")
        if not isinstance(self.availability, ObservationAvailability):
            raise TypeError("availability must be ObservationAvailability")
        _require_optional_reason(self.reason)

        groups = _ordered_tuple(self.block_groups, "block_groups")
        normalized_groups: list[tuple[NativeBlockSnapshot, ...]] = []
        for group_index, group_value in enumerate(groups):
            group = _ordered_tuple(group_value, f"block_groups[{group_index}]")
            if not all(isinstance(block, NativeBlockSnapshot) for block in group):
                raise TypeError("block_groups items must be NativeBlockSnapshot")
            non_null_block_ids = tuple(
                block.block_id for block in group if not block.is_null
            )
            if len(non_null_block_ids) != len(set(non_null_block_ids)):
                raise ValueError(
                    f"duplicate non-null block IDs in cache group {group_index}"
                )
            normalized_groups.append(group)  # type: ignore[arg-type]
        object.__setattr__(self, "block_groups", tuple(normalized_groups))

        if self.availability is ObservationAvailability.AVAILABLE:
            if self.reason is not None:
                raise ValueError("available snapshot must not have reason")
        else:
            if self.reason is None:
                raise ValueError("unavailable snapshot requires reason")
            if self.block_groups:
                raise ValueError("unavailable snapshot must not contain block groups")


@dataclass(frozen=True, slots=True)
class FreeQueueSnapshot:
    """Complete ordered copy of one native free queue."""

    blocks: tuple[NativeBlockSnapshot, ...]
    availability: ObservationAvailability
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.availability, ObservationAvailability):
            raise TypeError("availability must be ObservationAvailability")
        _require_optional_reason(self.reason)
        blocks = _ordered_tuple(self.blocks, "blocks")
        if not all(isinstance(block, NativeBlockSnapshot) for block in blocks):
            raise TypeError("blocks items must be NativeBlockSnapshot")
        block_ids = tuple(block.block_id for block in blocks)
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("duplicate block IDs in free queue")
        object.__setattr__(self, "blocks", blocks)

        if self.availability is ObservationAvailability.AVAILABLE:
            if self.reason is not None:
                raise ValueError("available snapshot must not have reason")
        else:
            if self.reason is None:
                raise ValueError("unavailable snapshot requires reason")
            if self.blocks:
                raise ValueError("unavailable snapshot must not contain blocks")


def snapshot_block(
    block: object,
    *,
    cache_group_id: int | None = None,
) -> NativeBlockSnapshot:
    """Copy the stable public observation fields of one native block."""

    block_id = _read_native_attribute(block, "block_id")
    ref_count = _read_native_attribute(block, "ref_cnt")
    native_hash = _read_native_attribute(block, "block_hash")
    hash_num_tokens = _read_native_attribute(block, "block_hash_num_tokens")
    is_null = _read_native_attribute(block, "is_null")

    native_hash_hex = None if native_hash is None else encode_native_hash(native_hash)
    return NativeBlockSnapshot(
        block_id=block_id,  # type: ignore[arg-type]
        ref_count=ref_count,  # type: ignore[arg-type]
        native_hash_hex=native_hash_hex,
        hash_num_tokens=hash_num_tokens,  # type: ignore[arg-type]
        cache_group_id=cache_group_id,
        is_null=is_null,  # type: ignore[arg-type]
    )


def snapshot_request_blocks(
    manager: object,
    *,
    request_id: RequestIdentity,
    program_id: ProgramIdentity,
) -> RequestBlockSnapshot:
    """Copy one live request mapping through vLLM's read-only ``get_blocks``."""

    _require_identity(program_id, ProgramIdentity, "program_id")
    _require_identity(request_id, RequestIdentity, "request_id")
    try:
        get_blocks = manager.get_blocks  # type: ignore[attr-defined]
    except AttributeError:
        return RequestBlockSnapshot(
            program_id=program_id,
            request_id=request_id,
            block_groups=(),
            availability=ObservationAvailability.UNAVAILABLE,
            reason="get_blocks is unavailable",
        )
    if not callable(get_blocks):
        return RequestBlockSnapshot(
            program_id=program_id,
            request_id=request_id,
            block_groups=(),
            availability=ObservationAvailability.UNAVAILABLE,
            reason="get_blocks is unavailable",
        )

    try:
        native_blocks = get_blocks(request_id.value)
    except KeyError:
        return RequestBlockSnapshot(
            program_id=program_id,
            request_id=request_id,
            block_groups=(),
            availability=ObservationAvailability.UNAVAILABLE,
            reason="request block mapping is unavailable",
        )

    try:
        native_groups = _native_ordered_tuple(
            _read_native_attribute(native_blocks, "blocks"), "native block groups"
        )
        groups = tuple(
            tuple(
                snapshot_block(block, cache_group_id=group_index)
                for block in _native_ordered_tuple(
                    group, f"native block group {group_index}"
                )
            )
            for group_index, group in enumerate(native_groups)
        )
    except _UnsupportedNativeShape as error:
        return RequestBlockSnapshot(
            program_id=program_id,
            request_id=request_id,
            block_groups=(),
            availability=ObservationAvailability.UNAVAILABLE,
            reason=str(error),
        )

    return RequestBlockSnapshot(
        program_id=program_id,
        request_id=request_id,
        block_groups=groups,
        availability=ObservationAvailability.AVAILABLE,
    )


def snapshot_free_queue(queue: object) -> FreeQueueSnapshot:
    """Walk a native free queue without invoking any queue mutator."""

    try:
        head = queue.fake_free_list_head  # type: ignore[attr-defined]
        tail = queue.fake_free_list_tail  # type: ignore[attr-defined]
        current = _read_native_attribute(head, "next_free_block")
    except (AttributeError, _UnsupportedNativeShape):
        return FreeQueueSnapshot(
            blocks=(),
            availability=ObservationAvailability.UNAVAILABLE,
            reason="free queue sentinels are unavailable",
        )

    snapshots: list[NativeBlockSnapshot] = []
    seen_objects: set[int] = set()
    try:
        while current is not tail:
            marker = id(current)
            if marker in seen_objects:
                return FreeQueueSnapshot(
                    blocks=(),
                    availability=ObservationAvailability.UNAVAILABLE,
                    reason="free queue contains a cycle",
                )
            seen_objects.add(marker)
            snapshots.append(snapshot_block(current))
            current = _read_native_attribute(current, "next_free_block")
    except _UnsupportedNativeShape as error:
        return FreeQueueSnapshot(
            blocks=(),
            availability=ObservationAvailability.UNAVAILABLE,
            reason=str(error),
        )

    return FreeQueueSnapshot(
        blocks=tuple(snapshots),
        availability=ObservationAvailability.AVAILABLE,
    )
