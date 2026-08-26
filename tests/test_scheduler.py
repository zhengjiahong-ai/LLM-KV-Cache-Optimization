from kvopt.scheduler.request import Request, RequestStatus
from kvopt.scheduler.scheduler import FIFOScheduler


def test_fifo_and_finished_requests_are_skipped() -> None:
    scheduler = FIFOScheduler()
    first = Request("first", 1, 1, 0.0)
    second = Request("second", 1, 1, 1.0)
    scheduler.add_request(first)
    scheduler.add_request(second)
    assert scheduler.schedule() is first
    assert first.status is RequestStatus.RUNNING
    scheduler.mark_finished("first")
    assert scheduler.schedule() is second
    scheduler.mark_finished("second")
    assert scheduler.schedule() is None
