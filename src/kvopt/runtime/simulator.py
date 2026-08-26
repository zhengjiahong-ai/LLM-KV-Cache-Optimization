"""Deterministic functional simulator, not a latency model."""

import math

from kvopt.kv_cache.manager import KVCacheManager
from kvopt.metrics.collector import MetricsCollector
from kvopt.scheduler.scheduler import FIFOScheduler


class Simulator:
    """Connect workload, scheduler, cache manager, policy, and metrics.

    This simulator is currently used for architecture validation and
    deterministic functional testing only. It does not predict LLM latency.
    """

    def __init__(self, scheduler: FIFOScheduler, cache: KVCacheManager, metrics: MetricsCollector) -> None:
        self.scheduler = scheduler
        self.cache = cache
        self.metrics = metrics
        self.current_time = 0.0
        self.completed_requests = 0

    def step(self) -> bool:
        request = self.scheduler.schedule(self.current_time)
        if request is None:
            return False
        total_tokens = request.prompt_tokens + request.generated_tokens + 1
        desired_blocks = math.ceil(total_tokens / self.cache.block_size_tokens)
        existing = next((item.num_blocks for item in self.cache.get_state().requests if item.request_id == request.request_id), 0)
        if desired_blocks > existing:
            self.cache.allocate(request.request_id, desired_blocks - existing, self.current_time, total_tokens)
        else:
            self.cache.access(request.request_id, self.current_time)
        request.generated_tokens += 1
        if request.is_complete:
            self.scheduler.mark_finished(request.request_id)
            self.cache.free(request.request_id)
            self.completed_requests += 1
            self.metrics.record("request_completion", request_id=request.request_id)
        self.metrics.record("cache_occupancy", occupied_blocks=self.cache.total_blocks - self.cache.get_state().free_blocks)
        self.current_time += 1.0
        return True

    def run(self) -> None:
        while self.step():
            pass
