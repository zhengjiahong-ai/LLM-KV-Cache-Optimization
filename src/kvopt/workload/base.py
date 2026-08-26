"""Input workload abstractions independent of a concrete dataset."""

from abc import ABC, abstractmethod
from collections.abc import Iterable

from kvopt.scheduler.request import Request


class Workload(ABC):
    @abstractmethod
    def requests(self) -> Iterable[Request]:
        """Yield input requests in deterministic trace order."""


class SyntheticWorkload(Workload):
    """A small fixed workload for demos and functional tests."""

    def __init__(self, num_requests: int = 5) -> None:
        self.num_requests = num_requests

    def requests(self) -> Iterable[Request]:
        for index in range(self.num_requests):
            yield Request(f"r{index + 1}", 16, 2, float(index))
