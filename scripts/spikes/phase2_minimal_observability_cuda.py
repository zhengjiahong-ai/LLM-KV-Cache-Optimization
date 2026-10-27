"""CUDA entry point for the shared vLLM V1 observation backend."""

from __future__ import annotations

from kvopt.profiling.experiment_events import ExperimentEventSink
from scripts.spikes.phase2_minimal_observability_metal import (
    MinimalMetalObservabilityBackend,
)


class MinimalCudaObservabilityBackend(MinimalMetalObservabilityBackend):
    """Named CUDA surface; shared policy and evidence behavior lives in the base."""


def build_phase2_cuda_observability_backend(
    config: dict[str, object],
    sink: ExperimentEventSink,
) -> MinimalCudaObservabilityBackend:
    if config.get("runtime_mode") != "vllm-cuda-observability":
        raise ValueError("CUDA backend requires runtime_mode=vllm-cuda-observability")
    return MinimalCudaObservabilityBackend(config, sink)
