from kvopt.kv_cache.manager import KVCacheManager
from kvopt.metrics.collector import MetricsCollector
from kvopt.policies.dummy import DummyEvictionPolicy
from kvopt.runtime.simulator import Simulator
from kvopt.scheduler.scheduler import FIFOScheduler
from kvopt.workload.base import SyntheticWorkload


def test_synthetic_pipeline_completes() -> None:
    metrics = MetricsCollector()
    cache = KVCacheManager(8, 16, DummyEvictionPolicy(), lambda kind, payload: metrics.record(kind, **payload))
    scheduler = FIFOScheduler()
    for request in SyntheticWorkload(3).requests():
        scheduler.add_request(request)
    simulator = Simulator(scheduler, cache, metrics)
    simulator.run()
    assert simulator.completed_requests == 3
    assert metrics.count("request_completion") == 3
    assert cache.get_state().free_blocks == 8
