"""Deterministic scheduling independent of cache eviction decisions."""

from kvopt.scheduler.request import Request, RequestStatus


class FIFOScheduler:
    """A minimal FIFO scheduler.

    It selects the earliest added unfinished request.  It intentionally knows
    nothing about cache capacity or eviction policy.
    """

    def __init__(self) -> None:
        self._requests: list[Request] = []

    def add_request(self, request: Request) -> None:
        if any(item.request_id == request.request_id for item in self._requests):
            raise ValueError(f"duplicate request id: {request.request_id}")
        self._requests.append(request)

    def schedule(self, current_time: float | None = None) -> Request | None:
        """Return the next runnable request, or ``None`` if all are finished."""
        del current_time  # Reserved for future arrival-time-aware scheduling.
        for request in self._requests:
            if request.status in (RequestStatus.WAITING, RequestStatus.RUNNING):
                request.status = RequestStatus.RUNNING
                return request
        return None

    def mark_finished(self, request_id: str) -> None:
        request = self._get(request_id)
        request.status = RequestStatus.FINISHED

    def _get(self, request_id: str) -> Request:
        for request in self._requests:
            if request.request_id == request_id:
                return request
        raise KeyError(request_id)
