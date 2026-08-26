"""Small, in-memory event collector intended for extension by evaluation work."""

from collections import Counter
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricEvent:
    event_type: str
    payload: dict[str, Any]


class MetricsCollector:
    def __init__(self) -> None:
        self.events: list[MetricEvent] = []
        self.peak_occupied_blocks = 0

    def record(self, event_type: str, **payload: Any) -> None:
        self.events.append(MetricEvent(event_type, payload))
        occupied = payload.get("occupied_blocks")
        if isinstance(occupied, int):
            self.peak_occupied_blocks = max(self.peak_occupied_blocks, occupied)

    def count(self, event_type: str) -> int:
        return Counter(event.event_type for event in self.events)[event_type]
