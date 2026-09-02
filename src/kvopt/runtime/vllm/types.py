"""Runtime-neutral data passed from vLLM into eviction policies."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvictionCandidate:
    """Immutable snapshot of one vLLM block eligible for eviction.

    The adapter intentionally exposes only fields already available from the
    validated vLLM APC path. Policy-specific metadata should be added only when
    its collection and semantics are frozen.
    """

    block_id: int
    ref_cnt: int
    has_block_hash: bool
    lru_rank: int


@dataclass(frozen=True, slots=True)
class EvictionContext:
    """Runtime state relevant to one victim-selection decision."""

    required_blocks: int
    free_blocks: int
    total_blocks: int
    timestamp: float
