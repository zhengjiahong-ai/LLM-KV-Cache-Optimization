"""Run the deterministic architecture-validation demo."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kvopt.kv_cache.manager import KVCacheManager
from kvopt.metrics.collector import MetricsCollector
from kvopt.policies.dummy import DummyEvictionPolicy
from kvopt.runtime.simulator import Simulator
from kvopt.scheduler.scheduler import FIFOScheduler
from kvopt.workload.base import SyntheticWorkload


def main() -> None:
    metrics = MetricsCollector()
    cache = KVCacheManager(4, 16, DummyEvictionPolicy(), lambda kind, payload: metrics.record(kind, **payload))
    scheduler = FIFOScheduler()
    for request in SyntheticWorkload().requests():
        scheduler.add_request(request)
        print(f"Added request {request.request_id}")
    runtime = Simulator(scheduler, cache, metrics)
    runtime.run()
    print(f"Completed requests: {runtime.completed_requests}")
    print(f"Evictions: {metrics.count('eviction')}")
    print(f"Peak cache blocks: {metrics.peak_occupied_blocks}")


if __name__ == "__main__":
    main()
