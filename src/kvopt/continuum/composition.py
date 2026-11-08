"""Explicit high-level composition for a profile-backed Continuum runtime."""

from __future__ import annotations

from kvopt.profiling.experiment_events import ExperimentEventSink

from .clock import Clock
from .config import ContinuumConfig
from .prefill_profile import load_prefill_reload_provider
from .runtime import RuntimeCoordinator, build_runtime
from .ttl import compute_default_ttl_seconds

REPRESENTATIVE_DEFAULT_TTL_TOKEN_COUNT = 256
SUPPORTED_PREFILL_PROFILE_VERSION = "v1"


def build_runtime_from_config(
    *,
    config: ContinuumConfig,
    clock: Clock,
    experiment_event_sink: ExperimentEventSink | None = None,
    history_observation_enabled: bool = False,
) -> RuntimeCoordinator:
    """Compose a profile-backed runtime from explicit deployment inputs."""
    if not isinstance(config, ContinuumConfig):
        raise TypeError("config must be ContinuumConfig")
    if not config.enabled:
        raise ValueError("enabled Continuum configuration is required")
    if config.prefill_profile_path is None:
        raise ValueError("prefill_profile_path is required")
    if config.prefill_profile_version != SUPPORTED_PREFILL_PROFILE_VERSION:
        raise ValueError(
            "prefill_profile_version must be "
            f"{SUPPORTED_PREFILL_PROFILE_VERSION}"
        )

    provider = load_prefill_reload_provider(config.prefill_profile_path)
    try:
        representative_seconds, _provenance = provider.estimate(
            REPRESENTATIVE_DEFAULT_TTL_TOKEN_COUNT
        )
    except ValueError as error:
        if "outside the supported profile range" not in str(error):
            raise
        (
            _representative_token_count,
            representative_seconds,
            _provenance,
        ) = provider.default_ttl_reference()
    default_ttl_seconds = compute_default_ttl_seconds(representative_seconds)

    return build_runtime(
        clock=clock,
        prefill_reload_provider=provider,
        default_ttl_seconds=default_ttl_seconds,
        duration_history_threshold=config.duration_history_threshold,
        queue_delay_window_size=config.queue_delay_window_size,
        experiment_event_sink=experiment_event_sink,
        history_observation_enabled=history_observation_enabled,
    )
