"""Validated operating-mode configuration for the Continuum baseline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .types import _require_non_empty_text, _require_optional_non_empty_text

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def _require_positive_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be int")
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


class RetentionMode(str, Enum):
    """KV-cache retention integration mode."""

    NATIVE = "native"
    SHADOW = "shadow"
    CONTROLLED = "controlled"


class SchedulerMode(str, Enum):
    """Waiting/admission scheduler integration mode."""

    NATIVE = "native"
    SHADOW = "shadow"
    CONTROLLED = "controlled"


@dataclass(frozen=True, slots=True)
class ContinuumConfig:
    """Top-level safe-mode gate for Phase 1B runtime integration."""

    enabled: bool = False
    retention_mode: RetentionMode = RetentionMode.NATIVE
    scheduler_mode: SchedulerMode = SchedulerMode.NATIVE
    duration_history_threshold: int = 100
    queue_delay_window_size: int = 100
    prefill_profile_path: str | None = None
    prefill_profile_version: str | None = None
    structured_logging_enabled: bool = False
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be bool")
        if not isinstance(self.retention_mode, RetentionMode):
            raise TypeError("retention_mode must be RetentionMode")
        if not isinstance(self.scheduler_mode, SchedulerMode):
            raise TypeError("scheduler_mode must be SchedulerMode")
        _require_positive_int(
            self.duration_history_threshold, "duration_history_threshold"
        )
        _require_positive_int(self.queue_delay_window_size, "queue_delay_window_size")
        _require_optional_non_empty_text(
            self.prefill_profile_path, "prefill_profile_path"
        )
        _require_optional_non_empty_text(
            self.prefill_profile_version, "prefill_profile_version"
        )
        if not isinstance(self.structured_logging_enabled, bool):
            raise TypeError("structured_logging_enabled must be bool")
        _require_non_empty_text(self.log_level, "log_level")
        if self.log_level not in _VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(_VALID_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {allowed}")
        if not self.enabled and (
            self.retention_mode is not RetentionMode.NATIVE
            or self.scheduler_mode is not SchedulerMode.NATIVE
        ):
            raise ValueError(
                "disabled Continuum configuration requires native retention and scheduler modes"
            )
