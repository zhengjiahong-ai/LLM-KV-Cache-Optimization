"""Request data model shared by workloads and the scheduler."""

from dataclasses import dataclass
from enum import Enum


class RequestStatus(str, Enum):
    WAITING = "waiting"
    RUNNING = "running"
    FINISHED = "finished"
    PREEMPTED = "preempted"


@dataclass
class Request:
    request_id: str
    prompt_tokens: int
    max_new_tokens: int
    arrival_time: float
    generated_tokens: int = 0
    status: RequestStatus = RequestStatus.WAITING

    @property
    def is_complete(self) -> bool:
        return self.generated_tokens >= self.max_new_tokens
