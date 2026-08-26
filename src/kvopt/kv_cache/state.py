"""Read-only snapshots supplied to eviction policies."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RequestCacheState:
    request_id: str
    num_blocks: int
    cached_tokens: int
    last_access_time: float


@dataclass(frozen=True)
class CacheState:
    total_blocks: int
    free_blocks: int
    requests: tuple[RequestCacheState, ...]
