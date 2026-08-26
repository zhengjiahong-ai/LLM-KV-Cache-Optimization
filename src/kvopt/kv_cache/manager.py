"""Logical block allocator; no GPU tensors are allocated here."""

from collections.abc import Callable

from kvopt.kv_cache.policy import EvictionPolicy
from kvopt.kv_cache.state import CacheState, RequestCacheState

EventSink = Callable[[str, dict[str, object]], None]


class KVCacheManager:
    """Own and expose the lifecycle of logical KV-cache blocks."""

    def __init__(
        self,
        total_blocks: int,
        block_size_tokens: int,
        policy: EvictionPolicy,
        event_sink: EventSink | None = None,
    ) -> None:
        if total_blocks <= 0 or block_size_tokens <= 0:
            raise ValueError("block counts and sizes must be positive")
        self.total_blocks = total_blocks
        self.block_size_tokens = block_size_tokens
        self.policy = policy
        self._free_blocks: set[int] = set(range(total_blocks))
        self._allocations: dict[str, set[int]] = {}
        self._cached_tokens: dict[str, int] = {}
        self._last_access: dict[str, float] = {}
        self._event_sink = event_sink

    def allocate(self, request_id: str, num_blocks: int, current_time: float, cached_tokens: int = 0) -> tuple[int, ...]:
        """Allocate additional blocks, evicting policy-selected requests if needed."""
        if num_blocks < 0:
            raise ValueError("num_blocks cannot be negative")
        if num_blocks > self.total_blocks:
            raise ValueError("a single allocation cannot exceed total capacity")
        shortfall = num_blocks - len(self._free_blocks)
        if shortfall > 0:
            victims = self.policy.select_victims(self.get_state(), shortfall, current_time)
            released = 0
            for victim in victims:
                if victim == request_id or victim not in self._allocations:
                    continue
                released += len(self._allocations[victim])
                self.free(victim, event_type="eviction")
                if released >= shortfall:
                    break
            if len(self._free_blocks) < num_blocks:
                raise RuntimeError("eviction policy did not release enough blocks")
        chosen = tuple(sorted(self._free_blocks)[:num_blocks])
        self._free_blocks.difference_update(chosen)
        self._allocations.setdefault(request_id, set()).update(chosen)
        self._cached_tokens[request_id] = cached_tokens
        self._last_access[request_id] = current_time
        self._emit("allocation", request_id=request_id, blocks=num_blocks)
        return chosen

    def free(self, request_id: str, event_type: str = "free") -> int:
        """Release all blocks owned by a request and return their count."""
        blocks = self._allocations.pop(request_id, set())
        self._free_blocks.update(blocks)
        self._cached_tokens.pop(request_id, None)
        self._last_access.pop(request_id, None)
        if blocks:
            self._emit(event_type, request_id=request_id, blocks=len(blocks))
        return len(blocks)

    def access(self, request_id: str, current_time: float) -> None:
        if request_id not in self._allocations:
            raise KeyError(f"request has no cache allocation: {request_id}")
        self._last_access[request_id] = current_time
        self._emit("access", request_id=request_id)

    def get_state(self) -> CacheState:
        requests = tuple(
            RequestCacheState(
                request_id=request_id,
                num_blocks=len(self._allocations[request_id]),
                cached_tokens=self._cached_tokens[request_id],
                last_access_time=self._last_access[request_id],
            )
            for request_id in sorted(self._allocations)
        )
        return CacheState(self.total_blocks, len(self._free_blocks), requests)

    def _emit(self, event_type: str, **payload: object) -> None:
        if self._event_sink is not None:
            self._event_sink(event_type, payload)
