"""Backend-neutral orchestration for one validated prefill MISS/HIT pair.

The native boundary is supplied by the caller.  This module intentionally does
not import vLLM or Metal so that its validation logic remains unit-testable.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

TOKEN_GRID = (16, 32, 128, 256, 512)


def run_prefill_pair(
    *,
    r: int,
    prefix_token_ids: Sequence[int],
    suffix_token_id: int,
    native: object,
    timer: Callable[[], float],
    diagnostics_sink: Callable[[Mapping[str, object]], None] | None = None,
    max_pressure_batches: int,
) -> tuple[float, float]:
    """Run and validate one corrected r+1 prefill pair.

    ``native`` is a narrow backend adapter.  It must provide target submission,
    stepping, idle detection, request observations, read-only target-material
    presence checks, and one ordinary pressure-batch operation.  The adapter is
    responsible for all vLLM/Metal-specific details.
    """

    _validate_inputs(
        r=r,
        prefix_token_ids=prefix_token_ids,
        suffix_token_id=suffix_token_id,
        native=native,
        timer=timer,
        diagnostics_sink=diagnostics_sink,
        max_pressure_batches=max_pressure_batches,
    )
    request_token_ids = tuple(prefix_token_ids) + (suffix_token_id,)
    if not native.read_target_material_presence():
        raise ValueError("target material is absent at pair entry")

    pressure_batches = 0
    target_present_after_pressure = True
    while pressure_batches < max_pressure_batches:
        native.run_pressure_batch()
        pressure_batches += 1
        target_present_after_pressure = native.read_target_material_presence()
        if not target_present_after_pressure:
            break
    if target_present_after_pressure:
        raise ValueError("pressure bound exhausted while target material remained present")

    miss_ttft, miss_request_id, miss_observation = _run_target(
        native=native,
        token_ids=request_token_ids,
        timer=timer,
    )
    _validate_miss(miss_observation)

    hit_ttft, hit_request_id, hit_observation = _run_target(
        native=native,
        token_ids=request_token_ids,
        timer=timer,
    )
    _validate_hit(hit_observation, r)

    if diagnostics_sink is not None:
        diagnostics_sink(
            {
                "r": r,
                "request_length": len(request_token_ids),
                "miss_request_id": miss_request_id,
                "hit_request_id": hit_request_id,
                "miss_num_cached_tokens": miss_observation.num_cached_tokens,
                "hit_num_cached_tokens": hit_observation.num_cached_tokens,
                "target_present_before_pressure": True,
                "target_present_after_pressure": False,
                "pressure_batches": pressure_batches,
                "miss_ttft_seconds": miss_ttft,
                "hit_ttft_seconds": hit_ttft,
            }
        )

    return miss_ttft, hit_ttft


def _validate_inputs(
    *,
    r: int,
    prefix_token_ids: Sequence[int],
    suffix_token_id: int,
    native: object,
    timer: Callable[[], float],
    diagnostics_sink: Callable[[Mapping[str, object]], None] | None,
    max_pressure_batches: int,
) -> None:
    if type(r) is not int or r not in TOKEN_GRID:
        raise ValueError("r must be one of the frozen profile points")
    if not isinstance(prefix_token_ids, Sequence) or isinstance(
        prefix_token_ids, (str, bytes)
    ):
        raise TypeError("prefix_token_ids must be a token sequence")
    if len(prefix_token_ids) != r:
        raise ValueError("prefix token count must equal r")
    if any(type(token_id) is not int for token_id in prefix_token_ids):
        raise TypeError("prefix token IDs must be integers")
    if type(suffix_token_id) is not int:
        raise TypeError("suffix token ID must be an integer")
    if not callable(timer):
        raise TypeError("timer must be callable")
    if diagnostics_sink is not None and not callable(diagnostics_sink):
        raise TypeError("diagnostics_sink must be callable")
    if type(max_pressure_batches) is not int or max_pressure_batches <= 0:
        raise ValueError("max_pressure_batches must be positive")
    for method_name in (
        "submit_target",
        "step",
        "is_idle",
        "request_observation",
        "read_target_material_presence",
        "run_pressure_batch",
    ):
        if not callable(getattr(native, method_name, None)):
            raise TypeError(f"native boundary lacks {method_name}")


def _run_target(
    *,
    native: object,
    token_ids: tuple[int, ...],
    timer: Callable[[], float],
) -> tuple[float, str, Any]:
    if not native.is_idle():
        raise ValueError("native engine is not idle before target submission")

    t0 = timer()
    request_id = native.submit_target(
        token_ids,
        max_tokens=1,
        temperature=0.0,
        seed=0,
    )
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("native target request ID is invalid")

    first_token_time: float | None = None
    while first_token_time is None:
        outputs = native.step()
        if outputs is None:
            raise ValueError("native step returned no output collection")
        for output in outputs:
            if getattr(output, "request_id", None) != request_id:
                continue
            generated_token_ids = getattr(output, "generated_token_ids", ())
            if generated_token_ids:
                first_token_time = timer()
                break
            if getattr(output, "finished", False):
                raise ValueError("target completed without a generated token")
        if first_token_time is None and native.is_idle():
            raise ValueError("target became idle before a generated token")

    while not native.is_idle():
        native.step()

    t1 = first_token_time
    if not math.isfinite(t0) or not math.isfinite(t1) or t1 < t0:
        raise ValueError("target TTFT timestamps are invalid")
    observation = native.request_observation(request_id)
    return t1 - t0, request_id, observation


def _validate_miss(observation: Any) -> None:
    if (
        observation.num_cached_tokens != 0
        or observation.prefix_material_created is not True
        or observation.prefix_material_reused is not False
    ):
        raise ValueError("native MISS evidence is invalid")


def _validate_hit(observation: Any, r: int) -> None:
    if (
        observation.num_cached_tokens != r
        or observation.prefix_material_created is not False
        or observation.prefix_material_reused is not True
    ):
        raise ValueError("native HIT evidence is invalid")
