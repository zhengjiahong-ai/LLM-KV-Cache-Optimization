"""Placeholder benchmark entry point for future workload work."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kvopt.metrics.collector import MetricsCollector
from kvopt.runtime.simulator import Simulator
from kvopt.scheduler.scheduler import FIFOScheduler
from kvopt.kv_cache.manager import KVCacheManager
from kvopt.policies.dummy import DummyEvictionPolicy
from kvopt.workload.base import SyntheticWorkload


def main() -> None:
    metrics = MetricsCollector()
    cache = KVCacheManager(128, 16, DummyEvictionPolicy(), lambda kind, payload: metrics.record(kind, **payload))
    scheduler = FIFOScheduler()
    for request in SyntheticWorkload(20).requests():
        scheduler.add_request(request)
    runtime = Simulator(scheduler, cache, metrics)
    runtime.run()
    print(f"Completed requests: {runtime.completed_requests}")


if __name__ == "__main__":
    main()
