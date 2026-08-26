"""KV cache optimization architecture scaffold."""

from kvopt.kv_cache.manager import KVCacheManager
from kvopt.scheduler.scheduler import FIFOScheduler

__all__ = ["FIFOScheduler", "KVCacheManager"]
