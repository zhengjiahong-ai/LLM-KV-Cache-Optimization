"""Content identity for the Phase 2F physical-block APC simulator.

Block content identity is a *chained* hash, mirroring vLLM prefix-hash
semantics: identical tokens at different prefix positions yield different
identities, so the content universe is a prefix trie rather than a flat set.
Sharing a deep block therefore implies sharing every ancestor block, which is
what makes per-block ``depth`` a well-defined content property.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Segment:
    """One block-aligned content unit of a request prompt."""

    key: str
    tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("segment key must be non-empty text")
        if isinstance(self.tokens, bool) or not isinstance(self.tokens, int):
            raise TypeError("segment tokens must be int")
        if self.tokens <= 0:
            raise ValueError("segment tokens must be positive")


def _chain_hash(previous: str, segment_key: str, index: int) -> str:
    payload = f"{previous}|{segment_key}|{index}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prompt_block_content_ids(segments: tuple[Segment, ...], block_size: int) -> tuple[str, ...]:
    """Return the chained content id of every **full** block of a prompt.

    Segments must be block aligned (token counts are multiples of
    ``block_size``); the generator enforces this and the simulator validates it.
    The last (possibly partial) block of the prompt is intentionally excluded:
    the frozen Phase 2E derivation caps the cacheable prefix at
    ``(prompt_tokens - 1) // block_size`` blocks.
    """
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    total_tokens = sum(segment.tokens for segment in segments)
    if total_tokens % block_size != 0:
        raise ValueError("prompt segments must be block aligned")
    full_blocks = (total_tokens - 1) // block_size if total_tokens > 0 else 0
    identities: list[str] = []
    previous = "root"
    block_index = 0
    for segment in segments:
        for _ in range(segment.tokens // block_size):
            if block_index >= full_blocks:
                return tuple(identities)
            previous = _chain_hash(previous, segment.key, block_index)
            identities.append(previous)
            block_index += 1
    return tuple(identities)
