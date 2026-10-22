"""Observation-only wrappers for the W1-A Mini-SWE-Agent acquisition pilot."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

SIDECAR_SCHEMA_VERSION = "continuum.w1a_acquisition_sidecar.v1"


class _Model(Protocol):
    def query(self, messages: list[dict[str, Any]]) -> dict[str, Any]: ...


class _Environment(Protocol):
    def execute(self, action: str) -> dict[str, str]: ...


TokenizeMessages = Callable[[Sequence[Mapping[str, Any]]], tuple[str, list[int]]]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finite_seconds(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


class AcquisitionRecorder:
    """Collect request and tool observations without controlling their execution."""

    def __init__(
        self,
        *,
        program_id: str,
        provenance: Mapping[str, object],
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        tokenize_messages: TokenizeMessages | None = None,
    ) -> None:
        if not program_id.strip():
            raise ValueError("program_id must be non-empty")
        self.program_id = program_id
        self.provenance = copy.deepcopy(dict(provenance))
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._tokenize_messages = tokenize_messages
        self.model_calls: list[dict[str, object]] = []
        self.tool_calls: list[dict[str, object]] = []

    def observe_model_call(
        self,
        messages: Sequence[Mapping[str, Any]],
        invoke: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        turn_index = len(self.model_calls) + 1
        request_id = f"{self.program_id}:turn:{turn_index}"
        copied_messages = copy.deepcopy([dict(message) for message in messages])
        rendered_prompt: str | None = None
        submitted_token_ids: list[int] | None = None
        token_status = "NOT_OBSERVED"
        if self._tokenize_messages is not None:
            rendered_prompt, submitted_token_ids = self._tokenize_messages(copied_messages)
            if not isinstance(rendered_prompt, str) or any(
                isinstance(item, bool) or not isinstance(item, int)
                for item in submitted_token_ids
            ):
                raise TypeError("tokenization observer returned invalid prompt or token IDs")
            token_status = "DETERMINISTIC_LOCAL_TOKENIZATION_NOT_RUNTIME_SUBMISSION"

        submit_monotonic = _finite_seconds(self._monotonic_clock(), "model submit time")
        submit_wall = _finite_seconds(self._wall_clock(), "model submit wall time")
        try:
            response = invoke()
        except BaseException as error:
            completion_monotonic = _finite_seconds(
                self._monotonic_clock(), "model completion time"
            )
            self.model_calls.append(
                {
                    "program_id": self.program_id,
                    "turn_index": turn_index,
                    "request_id": request_id,
                    "messages": copied_messages,
                    "messages_sha256": _sha256(copied_messages),
                    "rendered_prompt": rendered_prompt,
                    "submitted_token_ids": submitted_token_ids,
                    "token_observation_status": token_status,
                    "model_submit_monotonic_seconds": submit_monotonic,
                    "model_completion_monotonic_seconds": completion_monotonic,
                    "model_submit_unix_seconds": submit_wall,
                    "status": "FAILED",
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            raise
        completion_monotonic = _finite_seconds(
            self._monotonic_clock(), "model completion time"
        )
        if completion_monotonic < submit_monotonic:
            raise ValueError("model completion precedes submission")
        self.model_calls.append(
            {
                "program_id": self.program_id,
                "turn_index": turn_index,
                "request_id": request_id,
                "messages": copied_messages,
                "messages_sha256": _sha256(copied_messages),
                "rendered_prompt": rendered_prompt,
                "rendered_prompt_sha256": (
                    hashlib.sha256(rendered_prompt.encode()).hexdigest()
                    if rendered_prompt is not None
                    else None
                ),
                "submitted_token_ids": submitted_token_ids,
                "token_observation_status": token_status,
                "model_submit_monotonic_seconds": submit_monotonic,
                "model_completion_monotonic_seconds": completion_monotonic,
                "model_submit_unix_seconds": submit_wall,
                "status": "SUCCESS",
                "response_sha256": _sha256(response),
            }
        )
        return response

    def observe_tool_call(
        self,
        action: str,
        invoke: Callable[[], dict[str, str]],
    ) -> dict[str, str]:
        turn_index = len(self.model_calls)
        request_id = f"{self.program_id}:turn:{turn_index}"
        start = _finite_seconds(self._monotonic_clock(), "tool start time")
        try:
            result = invoke()
        except BaseException as error:
            end = _finite_seconds(self._monotonic_clock(), "tool completion time")
            self.tool_calls.append(
                {
                    "program_id": self.program_id,
                    "turn_index": turn_index,
                    "request_id": request_id,
                    "action": action,
                    "action_sha256": hashlib.sha256(action.encode()).hexdigest(),
                    "tool_start_monotonic_seconds": start,
                    "tool_completion_monotonic_seconds": end,
                    "status": "FAILED",
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            raise
        end = _finite_seconds(self._monotonic_clock(), "tool completion time")
        if end < start:
            raise ValueError("tool completion precedes start")
        self.tool_calls.append(
            {
                "program_id": self.program_id,
                "turn_index": turn_index,
                "request_id": request_id,
                "action": action,
                "action_sha256": hashlib.sha256(action.encode()).hexdigest(),
                "tool_start_monotonic_seconds": start,
                "tool_completion_monotonic_seconds": end,
                "status": "SUCCESS",
                "result_sha256": _sha256(result),
            }
        )
        return result

    def to_dict(self, *, trajectory_path: Path | None = None) -> dict[str, object]:
        trajectory_sha = None
        if trajectory_path is not None:
            trajectory_sha = hashlib.sha256(trajectory_path.read_bytes()).hexdigest()
        return {
            "schema_version": SIDECAR_SCHEMA_VERSION,
            "program_id": self.program_id,
            "provenance": copy.deepcopy(self.provenance),
            "trajectory_sha256": trajectory_sha,
            "model_calls": copy.deepcopy(self.model_calls),
            "tool_calls": copy.deepcopy(self.tool_calls),
            "observation_boundaries": {
                "model_times": "WRAPPER_BOUNDARY_MONOTONIC",
                "tool_times": "WRAPPER_BOUNDARY_MONOTONIC",
                "token_ids": (
                    "DETERMINISTIC_LOCAL_TOKENIZATION_NOT_RUNTIME_SUBMISSION"
                    if self._tokenize_messages is not None
                    else "NOT_OBSERVED"
                ),
                "native_apc_or_kv_residency": "NOT_OBSERVED",
            },
        }

    def write(self, path: Path, *, trajectory_path: Path | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(trajectory_path=trajectory_path), indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        return path


class ObservedModel:
    def __init__(self, model: _Model, recorder: AcquisitionRecorder) -> None:
        self._model = model
        self._recorder = recorder

    def query(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return self._recorder.observe_model_call(messages, lambda: self._model.query(messages))

    def __getattr__(self, name: str) -> object:
        return getattr(self._model, name)


class ObservedEnvironment:
    def __init__(self, environment: _Environment, recorder: AcquisitionRecorder) -> None:
        self._environment = environment
        self._recorder = recorder

    def execute(self, action: str) -> dict[str, str]:
        return self._recorder.observe_tool_call(
            action, lambda: self._environment.execute(action)
        )

    def __getattr__(self, name: str) -> object:
        return getattr(self._environment, name)
