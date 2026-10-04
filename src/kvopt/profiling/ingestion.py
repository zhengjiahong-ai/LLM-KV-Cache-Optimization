"""Load and validate raw Phase 2 experiment artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class ArtifactValidationError(ValueError):
    """Raised when raw experiment artifacts violate the data contract."""


_RUN_SCHEMA_VERSION = "phase2.run.v1"
_TRACE_SCHEMA_VERSION = "phase2.trace.v1"
_EVENT_SCHEMA_VERSION = "phase2.event.v1"

_REQUIRED_EVENT_FIELDS = (
    "schema_version",
    "run_id",
    "event_index",
    "event_type",
    "timestamp",
    "clock_domain",
    "source",
    "payload",
)


@dataclass(frozen=True, slots=True)
class RawRunArtifacts:
    """The four authoritative raw artifact sources for one run."""

    run_dir: Path
    run_id: str
    manifest: dict[str, object]
    trace: dict[str, object]
    replay: tuple[dict[str, object], ...]
    events: tuple[dict[str, object], ...]


def _load_json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ArtifactValidationError(
            f"{path.name} contains invalid JSON"
        ) from error

    if not isinstance(value, dict):
        raise ArtifactValidationError(
            f"{path.name} must contain a JSON object"
        )
    return value


def _load_jsonl_objects(path: Path) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []

    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue

        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ArtifactValidationError(
                f"{path.name} line {line_number} contains invalid JSON"
            ) from error

        if not isinstance(value, dict):
            raise ArtifactValidationError(
                f"{path.name} line {line_number} must contain a JSON object"
            )
        rows.append(value)

    return tuple(rows)


def _validate_events(
    events: tuple[dict[str, object], ...],
    run_id: str,
) -> None:
    previous_event_index: int | None = None

    for position, event in enumerate(events, start=1):
        for field in _REQUIRED_EVENT_FIELDS:
            if field not in event:
                raise ArtifactValidationError(
                    f"events.jsonl row {position} "
                    f"is missing required field: {field}"
                )

        if event["schema_version"] != _EVENT_SCHEMA_VERSION:
            raise ArtifactValidationError(
                f"events.jsonl row {position} "
                "has unsupported event schema_version"
            )

        event_run_id = event["run_id"]
        if event_run_id != run_id:
            raise ArtifactValidationError(
                f"events.jsonl row {position} has mismatched run_id"
            )

        event_index = event["event_index"]
        if (
            isinstance(event_index, bool)
            or not isinstance(event_index, int)
            or event_index < 0
        ):
            raise ArtifactValidationError(
                f"events.jsonl row {position} has invalid event_index"
            )

        if (
            previous_event_index is not None
            and event_index <= previous_event_index
        ):
            raise ArtifactValidationError(
                "event_index must be unique and strictly increasing"
            )

        previous_event_index = event_index


def load_run_artifacts(run_dir: str | Path) -> RawRunArtifacts:
    """Load and minimally validate one Phase 2 run directory."""

    directory = Path(run_dir)

    if not directory.is_dir():
        raise ArtifactValidationError(
            f"run directory does not exist: {directory}"
        )

    required_files = (
        "run.json",
        "trace.json",
        "replay.jsonl",
        "events.jsonl",
    )
    for filename in required_files:
        if not (directory / filename).is_file():
            raise ArtifactValidationError(
                f"required artifact is missing: {filename}"
            )

    manifest = _load_json_object(directory / "run.json")
    trace = _load_json_object(directory / "trace.json")
    replay = _load_jsonl_objects(directory / "replay.jsonl")
    events = _load_jsonl_objects(directory / "events.jsonl")

    if manifest.get("schema_version") != _RUN_SCHEMA_VERSION:
        raise ArtifactValidationError(
            "unsupported run schema_version"
        )

    if trace.get("schema_version") != _TRACE_SCHEMA_VERSION:
        raise ArtifactValidationError(
            "unsupported trace schema_version"
        )

    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ArtifactValidationError(
            "run.json must contain a non-empty run_id"
        )

    _validate_events(events, run_id)

    return RawRunArtifacts(
        run_dir=directory,
        run_id=run_id,
        manifest=manifest,
        trace=trace,
        replay=replay,
        events=events,
    )
