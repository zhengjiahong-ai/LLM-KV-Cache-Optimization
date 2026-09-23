import math
from dataclasses import FrozenInstanceError

import pytest

from kvopt.continuum import (
    Clock,
    ContinuumConfig,
    FakeClock,
    RetentionMode,
    SchedulerMode,
    SystemMonotonicClock,
)


def test_system_clock_satisfies_protocol_and_returns_valid_timestamp() -> None:
    clock = SystemMonotonicClock()

    assert isinstance(clock, Clock)
    first = clock.now()
    second = clock.now()
    assert math.isfinite(first)
    assert first >= 0.0
    assert second >= first


def test_fake_clock_satisfies_protocol_and_is_deterministic() -> None:
    clock = FakeClock(10)

    assert isinstance(clock, Clock)
    assert clock.now() == 10.0
    assert clock.advance(2.5) == 12.5
    assert clock.now() == 12.5
    clock.set(20)
    assert clock.now() == 20.0


@pytest.mark.parametrize(
    "invalid",
    [-1.0, math.inf, -math.inf, math.nan, True, "1.0", 10**400],
)
def test_fake_clock_rejects_invalid_initial_timestamp(invalid) -> None:
    with pytest.raises((TypeError, ValueError)):
        FakeClock(invalid)


@pytest.mark.parametrize(
    "invalid",
    [-1.0, math.inf, -math.inf, math.nan, True, "1.0", 10**400],
)
def test_fake_clock_rejects_invalid_advance(invalid) -> None:
    clock = FakeClock(1.0)

    with pytest.raises((TypeError, ValueError)):
        clock.advance(invalid)
    assert clock.now() == 1.0


def test_fake_clock_rejects_backwards_or_invalid_set() -> None:
    clock = FakeClock(2.0)

    with pytest.raises(ValueError, match="must not move backwards"):
        clock.set(1.0)
    with pytest.raises(ValueError, match="must be finite"):
        clock.set(math.nan)
    with pytest.raises(TypeError, match="must be a real number"):
        clock.set(True)
    assert clock.now() == 2.0


def test_fake_clock_rejects_overflow_without_mutating_state() -> None:
    clock = FakeClock(1.7e308)

    with pytest.raises(ValueError, match="must be finite"):
        clock.advance(1.7e308)
    assert clock.now() == 1.7e308


def test_default_config_is_safely_disabled_and_native() -> None:
    config = ContinuumConfig()

    assert config.enabled is False
    assert config.retention_mode is RetentionMode.NATIVE
    assert config.scheduler_mode is SchedulerMode.NATIVE
    assert config.duration_history_threshold == 100
    assert config.queue_delay_window_size == 100
    assert config.prefill_profile_path is None
    assert config.prefill_profile_version is None
    assert config.structured_logging_enabled is False
    assert config.log_level == "INFO"


def test_history_threshold_and_queue_window_are_independent() -> None:
    config = ContinuumConfig(
        duration_history_threshold=80,
        queue_delay_window_size=25,
    )

    assert config.duration_history_threshold == 80
    assert config.queue_delay_window_size == 25


@pytest.mark.parametrize("retention_mode", list(RetentionMode))
@pytest.mark.parametrize("scheduler_mode", list(SchedulerMode))
def test_enabled_config_accepts_every_explicit_mode_pair(
    retention_mode, scheduler_mode
) -> None:
    config = ContinuumConfig(
        enabled=True,
        retention_mode=retention_mode,
        scheduler_mode=scheduler_mode,
    )

    assert config.retention_mode is retention_mode
    assert config.scheduler_mode is scheduler_mode


@pytest.mark.parametrize(
    ("retention_mode", "scheduler_mode"),
    [
        (RetentionMode.SHADOW, SchedulerMode.NATIVE),
        (RetentionMode.CONTROLLED, SchedulerMode.NATIVE),
        (RetentionMode.NATIVE, SchedulerMode.SHADOW),
        (RetentionMode.NATIVE, SchedulerMode.CONTROLLED),
        (RetentionMode.SHADOW, SchedulerMode.CONTROLLED),
    ],
)
def test_disabled_config_rejects_non_native_modes(
    retention_mode, scheduler_mode
) -> None:
    with pytest.raises(ValueError, match="requires native retention and scheduler modes"):
        ContinuumConfig(
            enabled=False,
            retention_mode=retention_mode,
            scheduler_mode=scheduler_mode,
        )


@pytest.mark.parametrize("invalid", [0, 1, None, "false"])
def test_config_requires_boolean_enabled(invalid) -> None:
    with pytest.raises(TypeError, match="enabled must be bool"):
        ContinuumConfig(enabled=invalid)


@pytest.mark.parametrize(
    "field_name", ["duration_history_threshold", "queue_delay_window_size"]
)
@pytest.mark.parametrize("invalid", [0, -1, True, 1.0, "100", None])
def test_config_requires_positive_integer_window_values(field_name, invalid) -> None:
    with pytest.raises((TypeError, ValueError)):
        ContinuumConfig(**{field_name: invalid})


@pytest.mark.parametrize("field_name", ["prefill_profile_path", "prefill_profile_version"])
@pytest.mark.parametrize("invalid", ["", "   ", 1, True])
def test_config_rejects_invalid_optional_profile_metadata(field_name, invalid) -> None:
    with pytest.raises((TypeError, ValueError)):
        ContinuumConfig(**{field_name: invalid})


def test_config_accepts_explicit_profile_and_logging_metadata() -> None:
    config = ContinuumConfig(
        prefill_profile_path="profiles/a100.json",
        prefill_profile_version="v1",
        structured_logging_enabled=True,
        log_level="DEBUG",
    )

    assert config.prefill_profile_path == "profiles/a100.json"
    assert config.prefill_profile_version == "v1"
    assert config.structured_logging_enabled is True
    assert config.log_level == "DEBUG"


@pytest.mark.parametrize("invalid", [0, 1, None, "true"])
def test_config_requires_boolean_structured_logging_flag(invalid) -> None:
    with pytest.raises(TypeError, match="structured_logging_enabled must be bool"):
        ContinuumConfig(structured_logging_enabled=invalid)


@pytest.mark.parametrize(
    "invalid",
    ["", "   ", "debug", "WARN", "NOTSET", 20, None],
)
def test_config_rejects_invalid_log_level(invalid) -> None:
    with pytest.raises((TypeError, ValueError)):
        ContinuumConfig(log_level=invalid)


def test_config_rejects_strings_and_cross_domain_mode_enums() -> None:
    with pytest.raises(TypeError, match="retention_mode must be RetentionMode"):
        ContinuumConfig(enabled=True, retention_mode="shadow")
    with pytest.raises(TypeError, match="scheduler_mode must be SchedulerMode"):
        ContinuumConfig(enabled=True, scheduler_mode="controlled")
    with pytest.raises(TypeError, match="retention_mode must be RetentionMode"):
        ContinuumConfig(enabled=True, retention_mode=SchedulerMode.SHADOW)
    with pytest.raises(TypeError, match="scheduler_mode must be SchedulerMode"):
        ContinuumConfig(enabled=True, scheduler_mode=RetentionMode.SHADOW)


def test_config_is_immutable_and_modes_have_frozen_values() -> None:
    config = ContinuumConfig(enabled=True)

    assert {mode.value for mode in RetentionMode} == {"native", "shadow", "controlled"}
    assert {mode.value for mode in SchedulerMode} == {"native", "shadow", "controlled"}
    with pytest.raises(FrozenInstanceError):
        config.enabled = False
