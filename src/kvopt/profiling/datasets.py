"""Build derived Phase 2A profiling datasets from raw artifacts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .ingestion import ArtifactValidationError, RawRunArtifacts


@dataclass(frozen=True, slots=True)
class RunRow:
    """One row in the derived runs table."""

    run_id: str
    source_run_dir: str
    status: str
    failure_reason: str | None
    git_sha: str | None
    git_dirty: bool | None
    trace_id: str
    trace_sha256: str
    config_sha256: str
    seed: int
    policy: str
    runtime_mode: str
    scenario_id: str | None
    backend: str
    backend_revision: str
    model_name: str
    model_revision: str
    tokenizer_name: str
    tokenizer_revision: str
    platform: str
    started_at_utc: str | None
    ended_at_utc: str | None
    event_count: int
    forced_release_event_count: int
    observation_availability: dict[str, object]


def _required_mapping(
    value: object,
    field_name: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ArtifactValidationError(
            f"{field_name} must be an object"
        )
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactValidationError(
            f"{field_name} must be non-empty text"
        )
    return value


def _optional_text(
    value: object,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _required_non_negative_int(
    value: object,
    field_name: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ArtifactValidationError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _optional_bool(
    value: object,
    field_name: str,
) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ArtifactValidationError(
            f"{field_name} must be bool or null"
        )
    return value


def _build_run_row(artifacts: RawRunArtifacts) -> RunRow:
    manifest = artifacts.manifest

    config = _required_mapping(
        manifest.get("config"),
        "run.json config",
    )
    model = _required_mapping(
        manifest.get("model"),
        "run.json model",
    )
    tokenizer = _required_mapping(
        manifest.get("tokenizer"),
        "run.json tokenizer",
    )
    availability = _required_mapping(
        manifest.get("observation_availability"),
        "run.json observation_availability",
    )

    manifest_run_id = _required_text(
        manifest.get("run_id"),
        "run.json run_id",
    )
    if manifest_run_id != artifacts.run_id:
        raise ArtifactValidationError(
            "artifact run_id does not match run.json run_id"
        )

    return RunRow(
        run_id=artifacts.run_id,
        source_run_dir=str(artifacts.run_dir),
        status=_required_text(
            manifest.get("status"),
            "run.json status",
        ),
        failure_reason=_optional_text(
            manifest.get("failure_reason"),
            "run.json failure_reason",
        ),
        git_sha=_optional_text(
            manifest.get("git_sha"),
            "run.json git_sha",
        ),
        git_dirty=_optional_bool(
            manifest.get("git_dirty"),
            "run.json git_dirty",
        ),
        trace_id=_required_text(
            manifest.get("trace_id"),
            "run.json trace_id",
        ),
        trace_sha256=_required_text(
            manifest.get("trace_sha256"),
            "run.json trace_sha256",
        ),
        config_sha256=_required_text(
            manifest.get("config_sha256"),
            "run.json config_sha256",
        ),
        seed=_required_non_negative_int(
            manifest.get("seed"),
            "run.json seed",
        ),
        policy=_required_text(
            config.get("policy"),
            "run.json config.policy",
        ),
        runtime_mode=_required_text(
            config.get("runtime_mode"),
            "run.json config.runtime_mode",
        ),
        scenario_id=_optional_text(
            config.get("profiling_scenario_id"),
            "run.json config.profiling_scenario_id",
        ),
        backend=_required_text(
            manifest.get("backend"),
            "run.json backend",
        ),
        backend_revision=_required_text(
            manifest.get("backend_revision"),
            "run.json backend_revision",
        ),
        model_name=_required_text(
            model.get("name"),
            "run.json model.name",
        ),
        model_revision=_required_text(
            model.get("revision"),
            "run.json model.revision",
        ),
        tokenizer_name=_required_text(
            tokenizer.get("name"),
            "run.json tokenizer.name",
        ),
        tokenizer_revision=_required_text(
            tokenizer.get("revision"),
            "run.json tokenizer.revision",
        ),
        platform=_required_text(
            manifest.get("platform"),
            "run.json platform",
        ),
        started_at_utc=_optional_text(
            manifest.get("started_at_utc"),
            "run.json started_at_utc",
        ),
        ended_at_utc=_optional_text(
            manifest.get("ended_at_utc"),
            "run.json ended_at_utc",
        ),
        event_count=_required_non_negative_int(
            manifest.get("event_count"),
            "run.json event_count",
        ),
        forced_release_event_count=_required_non_negative_int(
            manifest.get("persisted_forced_release_event_count"),
            "run.json persisted_forced_release_event_count",
        ),
        observation_availability=dict(availability),
    )


def build_runs_table(
    runs: Iterable[RawRunArtifacts],
) -> tuple[RunRow, ...]:
    """Construct one provenance row per raw run."""

    rows: list[RunRow] = []
    seen_run_ids: set[str] = set()

    for artifacts in runs:
        if not isinstance(artifacts, RawRunArtifacts):
            raise TypeError(
                "runs must contain RawRunArtifacts instances"
            )

        if artifacts.run_id in seen_run_ids:
            raise ArtifactValidationError(
                f"duplicate run_id: {artifacts.run_id}"
            )

        seen_run_ids.add(artifacts.run_id)
        rows.append(_build_run_row(artifacts))

    return tuple(rows)