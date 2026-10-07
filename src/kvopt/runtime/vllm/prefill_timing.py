"""Profiling-only synchronization seam for isolated Metal prefill timing."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any, Self


class IsolatedPrefillTimingHook:
    """Synchronize a single paged prefill before sampling and record elapsed time."""

    _INSTALLED_MARKER = "_kvopt_isolated_prefill_timing_installed"
    _CONTEXT_ATTRIBUTE = "_kvopt_isolated_prefill_request_id"

    def __init__(
        self,
        runner_class: type[Any],
        synchronize: Callable[..., None],
        recorder: Callable[[str, float], None],
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._runner_class = runner_class
        self._synchronize = synchronize
        self._recorder = recorder
        self._clock = clock
        self._original_start: Callable[..., Any] | None = None
        self._original_submit: Callable[..., Any] | None = None

    def __enter__(self) -> Self:
        runner_class = self._runner_class
        if getattr(runner_class, self._INSTALLED_MARKER, False):
            raise RuntimeError("isolated prefill timing hook is already installed")
        original_start = runner_class._start_paged_forward
        original_submit = runner_class._submit_paged_forward_outputs
        synchronize = self._synchronize
        recorder = self._recorder
        clock = self._clock
        context_attribute = self._CONTEXT_ATTRIBUTE

        def timed_start(
            runner: Any,
            batch: Any,
            prefill_reqs: list[Any],
            decode_reqs: list[Any],
            scheduler_output: Any,
        ) -> Any:
            if len(prefill_reqs) != 1 or decode_reqs:
                raise RuntimeError(
                    "isolated prefill timing requires one prefill and no decode"
                )
            request_id = getattr(prefill_reqs[0], "req_id", None)
            if not isinstance(request_id, str) or not request_id:
                raise RuntimeError("isolated prefill request ID is unavailable")
            if getattr(runner, context_attribute, None) is not None:
                raise RuntimeError("isolated prefill timing context is already active")
            setattr(runner, context_attribute, request_id)
            try:
                return original_start(
                    runner,
                    batch,
                    prefill_reqs,
                    decode_reqs,
                    scheduler_output,
                )
            finally:
                setattr(runner, context_attribute, None)

        def timed_submit(runner: Any, *outputs: Any) -> Any:
            request_id = getattr(runner, context_attribute, None)
            if request_id is None:
                raise RuntimeError("prefill forward submitted outside timing context")
            started = clock()
            result = original_submit(runner, *outputs)
            synchronize(*outputs)
            elapsed = clock() - started
            if not math.isfinite(elapsed) or elapsed <= 0:
                raise RuntimeError("isolated prefill elapsed time must be positive")
            recorder(request_id, elapsed)
            return result

        self._original_start = original_start
        self._original_submit = original_submit
        runner_class._start_paged_forward = timed_start
        runner_class._submit_paged_forward_outputs = timed_submit
        setattr(runner_class, self._INSTALLED_MARKER, True)
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._original_start is None or self._original_submit is None:
            return
        self._runner_class._start_paged_forward = self._original_start
        self._runner_class._submit_paged_forward_outputs = self._original_submit
        setattr(self._runner_class, self._INSTALLED_MARKER, False)
        self._original_start = None
        self._original_submit = None
