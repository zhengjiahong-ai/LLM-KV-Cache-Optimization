"""Build derived Phase 2A profiling datasets from raw artifacts."""

from __future__ import annotations

import math
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


@dataclass(frozen=True, slots=True)
class DecisionRow:
    """One forced-release decision."""

    run_id: str
    decision_event_index: int
    source_event_index: int
    timestamp: float
    clock_domain: str
    source: str
    required_blocks: int
    candidate_count: int
    selected_release_count: int
    original_free_queue_count: int
    ordinary_expired_entry_count: int


@dataclass(frozen=True, slots=True)
class DecisionCandidateRow:
    """One candidate observed at one forced-release decision."""

    run_id: str
    decision_event_index: int
    source_event_index: int
    candidate_position: int
    program_id: str
    prefix_id: str
    selected: bool
    release_order: int | None
    retention_deadline_timestamp: float
    waiting_followup: bool
    block_ids: tuple[int, ...]
    block_count: int
    initially_reclaimable_block_ids: tuple[int, ...]
    initially_reclaimable_block_count: int
    next_tool_type: str | None
    elapsed_since_ttl_decision_seconds: float
    prefill_reload_seconds: float
    eta: float
    queue_delay_t_seconds: float


@dataclass(frozen=True, slots=True)
class DecisionTables:
    """The decision-level and candidate-level derived tables."""

    decisions: tuple[DecisionRow, ...]
    candidates: tuple[DecisionCandidateRow, ...]


@dataclass(frozen=True, slots=True)
class LogicalReleaseRow:
    """One logical protection release selected at a decision."""

    run_id: str
    decision_event_index: int
    source_event_index: int
    release_order: int
    program_id: str
    prefix_id: str
    newly_eligible_block_ids: tuple[int, ...]
    newly_eligible_block_count: int


@dataclass(frozen=True, slots=True)
class PhysicalEvictionRow:
    """One observed physical eviction, keyed by its source event."""

    run_id: str
    eviction_event_index: int
    source_event_index: int
    timestamp: float
    clock_domain: str
    source: str
    block_id: int
    preceding_decision_event_index: int | None
    native_hash_hex: str | None
    identity_kind: str


def _required_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ArtifactValidationError(f"{field_name} must be a list")
    return value


def _required_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ArtifactValidationError(f"{field_name} must be bool")
    return value


def _required_non_negative_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactValidationError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ArtifactValidationError(
            f"{field_name} must be finite and non-negative"
        )
    return number


def _required_block_ids(value: object, field_name: str) -> tuple[int, ...]:
    raw_ids = _required_list(value, field_name)
    block_ids: list[int] = []
    for block_id in raw_ids:
        block_ids.append(
            _required_non_negative_int(block_id, f"{field_name} item")
        )
    if len(block_ids) != len(set(block_ids)):
        raise ArtifactValidationError(f"{field_name} must not contain duplicates")
    return tuple(block_ids)


def _selected_release_order(
    selected_releases: list[object],
    event_index: int,
) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for order, raw_release in enumerate(selected_releases, start=1):
        release = _required_mapping(
            raw_release,
            f"decision {event_index} selected release {order}",
        )
        key = (
            _required_text(
                release.get("program_id"),
                f"decision {event_index} selected release program_id",
            ),
            _required_text(
                release.get("prefix_id"),
                f"decision {event_index} selected release prefix_id",
            ),
        )
        if key in result:
            raise ArtifactValidationError(
                f"decision {event_index} contains duplicate selected release"
            )
        result[key] = order
    return result


def _candidate_row(
    *,
    artifacts: RawRunArtifacts,
    event_index: int,
    position: int,
    raw_candidate: object,
    selected_order: dict[tuple[str, str], int],
) -> DecisionCandidateRow:
    field_prefix = f"decision {event_index} candidate {position}"
    candidate = _required_mapping(raw_candidate, field_prefix)
    program_id = _required_text(
        candidate.get("program_id"),
        f"{field_prefix} program_id",
    )
    prefix_id = _required_text(
        candidate.get("prefix_id"),
        f"{field_prefix} prefix_id",
    )
    block_ids = _required_block_ids(
        candidate.get("block_ids"),
        f"{field_prefix} block_ids",
    )
    reclaimable = _required_block_ids(
        candidate.get("initially_reclaimable_block_ids"),
        f"{field_prefix} initially_reclaimable_block_ids",
    )
    if not set(reclaimable).issubset(block_ids):
        raise ArtifactValidationError(
            f"{field_prefix} reclaimable blocks must belong to candidate"
        )
    key = (program_id, prefix_id)
    release_order = selected_order.get(key)

    return DecisionCandidateRow(
        run_id=artifacts.run_id,
        decision_event_index=event_index,
        source_event_index=event_index,
        candidate_position=position,
        program_id=program_id,
        prefix_id=prefix_id,
        selected=release_order is not None,
        release_order=release_order,
        retention_deadline_timestamp=_required_non_negative_float(
            candidate.get("retention_deadline_timestamp"),
            f"{field_prefix} retention_deadline_timestamp",
        ),
        waiting_followup=_required_bool(
            candidate.get("waiting_followup"),
            f"{field_prefix} waiting_followup",
        ),
        block_ids=block_ids,
        block_count=len(block_ids),
        initially_reclaimable_block_ids=reclaimable,
        initially_reclaimable_block_count=len(reclaimable),
        next_tool_type=_optional_text(
            candidate.get("next_tool_type"),
            f"{field_prefix} next_tool_type",
        ),
        elapsed_since_ttl_decision_seconds=_required_non_negative_float(
            candidate.get("elapsed_since_ttl_decision_seconds"),
            f"{field_prefix} elapsed_since_ttl_decision_seconds",
        ),
        prefill_reload_seconds=_required_non_negative_float(
            candidate.get("prefill_reload_seconds"),
            f"{field_prefix} prefill_reload_seconds",
        ),
        eta=_required_non_negative_float(
            candidate.get("eta"),
            f"{field_prefix} eta",
        ),
        queue_delay_t_seconds=_required_non_negative_float(
            candidate.get("queue_delay_t_seconds"),
            f"{field_prefix} queue_delay_t_seconds",
        ),
    )


def build_decision_tables(
    runs: Iterable[RawRunArtifacts],
) -> DecisionTables:
    """Expand forced-release events into decision and candidate rows."""

    decisions: list[DecisionRow] = []
    candidates: list[DecisionCandidateRow] = []
    seen_decision_keys: set[tuple[str, int]] = set()

    for artifacts in runs:
        if not isinstance(artifacts, RawRunArtifacts):
            raise TypeError("runs must contain RawRunArtifacts instances")

        for event in artifacts.events:
            if event.get("event_type") != "FORCED_RELEASE_DECISION":
                continue

            event_index = _required_non_negative_int(
                event.get("event_index"),
                "forced-release event_index",
            )
            decision_key = (artifacts.run_id, event_index)
            if decision_key in seen_decision_keys:
                raise ArtifactValidationError(
                    f"duplicate decision key: {decision_key}"
                )
            seen_decision_keys.add(decision_key)

            payload = _required_mapping(
                event.get("payload"),
                f"decision {event_index} payload",
            )
            raw_candidates = _required_list(
                payload.get("candidates"),
                f"decision {event_index} candidates",
            )
            raw_releases = _required_list(
                payload.get("selected_releases"),
                f"decision {event_index} selected_releases",
            )
            free_queue = _required_list(
                payload.get("original_free_queue"),
                f"decision {event_index} original_free_queue",
            )
            expired_entries = _required_list(
                payload.get("ordinary_expired_entries"),
                f"decision {event_index} ordinary_expired_entries",
            )
            selected_order = _selected_release_order(raw_releases, event_index)

            decision_candidates: list[DecisionCandidateRow] = []
            candidate_keys: set[tuple[str, str]] = set()
            for position, raw_candidate in enumerate(raw_candidates):
                row = _candidate_row(
                    artifacts=artifacts,
                    event_index=event_index,
                    position=position,
                    raw_candidate=raw_candidate,
                    selected_order=selected_order,
                )
                candidate_key = (row.program_id, row.prefix_id)
                if candidate_key in candidate_keys:
                    raise ArtifactValidationError(
                        f"decision {event_index} contains duplicate candidate"
                    )
                candidate_keys.add(candidate_key)
                decision_candidates.append(row)

            unknown_releases = set(selected_order).difference(candidate_keys)
            if unknown_releases:
                raise ArtifactValidationError(
                    f"decision {event_index} selected release is not a candidate"
                )

            decisions.append(
                DecisionRow(
                    run_id=artifacts.run_id,
                    decision_event_index=event_index,
                    source_event_index=event_index,
                    timestamp=_required_non_negative_float(
                        event.get("timestamp"),
                        f"decision {event_index} timestamp",
                    ),
                    clock_domain=_required_text(
                        event.get("clock_domain"),
                        f"decision {event_index} clock_domain",
                    ),
                    source=_required_text(
                        event.get("source"),
                        f"decision {event_index} source",
                    ),
                    required_blocks=_required_non_negative_int(
                        payload.get("required_blocks"),
                        f"decision {event_index} required_blocks",
                    ),
                    candidate_count=len(decision_candidates),
                    selected_release_count=len(raw_releases),
                    original_free_queue_count=len(free_queue),
                    ordinary_expired_entry_count=len(expired_entries),
                )
            )
            candidates.extend(decision_candidates)

    return DecisionTables(
        decisions=tuple(decisions),
        candidates=tuple(candidates),
    )


def build_logical_releases_table(
    runs: Iterable[RawRunArtifacts],
) -> tuple[LogicalReleaseRow, ...]:
    """Expand selected releases without treating them as physical evictions."""

    raw_runs = tuple(runs)
    decision_tables = build_decision_tables(raw_runs)
    candidate_blocks = {
        (
            row.run_id,
            row.decision_event_index,
            row.program_id,
            row.prefix_id,
        ): row.block_ids
        for row in decision_tables.candidates
    }
    rows: list[LogicalReleaseRow] = []

    for artifacts in raw_runs:
        for event in artifacts.events:
            if event.get("event_type") != "FORCED_RELEASE_DECISION":
                continue

            event_index = _required_non_negative_int(
                event.get("event_index"),
                "forced-release event_index",
            )
            payload = _required_mapping(
                event.get("payload"),
                f"decision {event_index} payload",
            )
            releases = _required_list(
                payload.get("selected_releases"),
                f"decision {event_index} selected_releases",
            )

            for order, raw_release in enumerate(releases, start=1):
                field_prefix = f"decision {event_index} selected release {order}"
                release = _required_mapping(raw_release, field_prefix)
                program_id = _required_text(
                    release.get("program_id"),
                    f"{field_prefix} program_id",
                )
                prefix_id = _required_text(
                    release.get("prefix_id"),
                    f"{field_prefix} prefix_id",
                )
                newly_eligible = _required_block_ids(
                    release.get("newly_eligible_block_ids"),
                    f"{field_prefix} newly_eligible_block_ids",
                )
                candidate_key = (
                    artifacts.run_id,
                    event_index,
                    program_id,
                    prefix_id,
                )
                owned_blocks = candidate_blocks[candidate_key]
                if not set(newly_eligible).issubset(owned_blocks):
                    raise ArtifactValidationError(
                        f"{field_prefix} newly eligible blocks "
                        "must belong to the selected candidate"
                    )

                rows.append(
                    LogicalReleaseRow(
                        run_id=artifacts.run_id,
                        decision_event_index=event_index,
                        source_event_index=event_index,
                        release_order=order,
                        program_id=program_id,
                        prefix_id=prefix_id,
                        newly_eligible_block_ids=newly_eligible,
                        newly_eligible_block_count=len(newly_eligible),
                    )
                )

    return tuple(rows)


def build_physical_evictions_table(
    runs: Iterable[RawRunArtifacts],
) -> tuple[PhysicalEvictionRow, ...]:
    """Preserve physical eviction events without treating block IDs as content IDs."""

    rows: list[PhysicalEvictionRow] = []
    seen_event_keys: set[tuple[str, int]] = set()

    for artifacts in runs:
        if not isinstance(artifacts, RawRunArtifacts):
            raise TypeError("runs must contain RawRunArtifacts instances")

        preceding_decision_event_index: int | None = None
        for event in artifacts.events:
            event_index = _required_non_negative_int(
                event.get("event_index"),
                "event_index",
            )
            event_type = event.get("event_type")
            if event_type == "FORCED_RELEASE_DECISION":
                preceding_decision_event_index = event_index
                continue
            if event_type != "BLOCK_EVICTED":
                continue

            event_key = (artifacts.run_id, event_index)
            if event_key in seen_event_keys:
                raise ArtifactValidationError(
                    f"duplicate physical eviction event key: {event_key}"
                )
            seen_event_keys.add(event_key)

            payload = _required_mapping(
                event.get("payload"),
                f"physical eviction {event_index} payload",
            )
            native_hash_hex = _optional_text(
                payload.get("native_hash_hex"),
                f"physical eviction {event_index} native_hash_hex",
            )
            rows.append(
                PhysicalEvictionRow(
                    run_id=artifacts.run_id,
                    eviction_event_index=event_index,
                    source_event_index=event_index,
                    timestamp=_required_non_negative_float(
                        event.get("timestamp"),
                        f"physical eviction {event_index} timestamp",
                    ),
                    clock_domain=_required_text(
                        event.get("clock_domain"),
                        f"physical eviction {event_index} clock_domain",
                    ),
                    source=_required_text(
                        event.get("source"),
                        f"physical eviction {event_index} source",
                    ),
                    block_id=_required_non_negative_int(
                        payload.get("block_id"),
                        f"physical eviction {event_index} block_id",
                    ),
                    preceding_decision_event_index=(
                        preceding_decision_event_index
                    ),
                    native_hash_hex=native_hash_hex,
                    identity_kind=(
                        "native_hash"
                        if native_hash_hex is not None
                        else "block_slot_only"
                    ),
                )
            )

    return tuple(rows)
