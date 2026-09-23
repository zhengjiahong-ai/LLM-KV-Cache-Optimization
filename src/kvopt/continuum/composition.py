"""Explicit high-level composition for a profile-backed Continuum runtime."""

from __future__ import annotations

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
    representative_seconds, _provenance = provider.estimate(
        REPRESENTATIVE_DEFAULT_TTL_TOKEN_COUNT
    )
    default_ttl_seconds = compute_default_ttl_seconds(representative_seconds)

    return build_runtime(
        clock=clock,
        prefill_reload_provider=provider,
        default_ttl_seconds=default_ttl_seconds,
        duration_history_threshold=config.duration_history_threshold,
        queue_delay_window_size=config.queue_delay_window_size,
    )
