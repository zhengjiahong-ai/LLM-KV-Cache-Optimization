"""Join decision candidates to future lifecycle outcomes without leakage."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from .datasets import DecisionCandidateRow, DecisionRow, build_decision_tables
from .ingestion import ArtifactValidationError, RawRunArtifacts


@dataclass(frozen=True, slots=True)
class DecisionOutcomeRow:
    """Future outcome for one candidate at one forced-release decision."""

    run_id: str
    decision_event_index: int
    program_id: str
    prefix_id: str
    selected: bool
    return_request_id: str | None
    return_arrival_event_index: int | None
    return_arrival_timestamp: float | None
    return_arrival_clock_domain: str | None
    returned_after_decision: bool
    event_distance_to_return: int | None
    time_to_return_seconds: float | None
    time_to_return_status: str
    analysis_horizon_seconds: float | None
    returned_within_horizon: bool | None
    return_horizon_status: str
    return_prefix_snapshot_event_index: int | None
    same_prefix_reobserved: bool | None
    physical_eviction_event_indexes: tuple[int, ...]
    physical_eviction_count: int
    physical_eviction_match_status: str


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactValidationError(f"{field_name} must be non-empty text")
    return value


def _index(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactValidationError(
            f"{field_name} must be a non-negative integer"
        )
    return value


def _timestamp(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactValidationError(f"{field_name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ArtifactValidationError(
            f"{field_name} must be finite and non-negative"
        )
    return result


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ArtifactValidationError(f"{field_name} must be an object")
    return value


def _block_ids(event: dict[str, object]) -> tuple[int, ...]:
    payload = _mapping(event.get("payload"), "block observation payload")
    raw_ids = payload.get("block_ids")
    if not isinstance(raw_ids, list):
        raise ArtifactValidationError("block observation block_ids must be a list")
    result = tuple(_index(value, "block observation block_id") for value in raw_ids)
    if len(result) != len(set(result)):
        raise ArtifactValidationError(
            "block observation block_ids must not contain duplicates"
        )
    return result


def _first_future_return(
    events: tuple[dict[str, object], ...],
    candidate: DecisionCandidateRow,
) -> dict[str, object] | None:
    for event in events:
        event_index = _index(event.get("event_index"), "event_index")
        if event_index <= candidate.decision_event_index:
            continue
        if (
            event.get("event_type") == "REQUEST_ARRIVED"
            and event.get("program_id") == candidate.program_id
        ):
            return event
    return None


def _return_prefix_snapshot(
    events: tuple[dict[str, object], ...],
    return_event: dict[str, object] | None,
) -> dict[str, object] | None:
    if return_event is None:
        return None
    request_id = _text(return_event.get("request_id"), "return request_id")
    return_index = _index(return_event.get("event_index"), "return event_index")
    for event in events:
        event_index = _index(event.get("event_index"), "event_index")
        if event_index <= return_index:
            continue
        if (
            event.get("event_type") == "VLLM_PREFIX_SNAPSHOT"
            and event.get("request_id") == request_id
        ):
            return event
    return None


def _time_to_return(
    decision: DecisionRow,
    return_event: dict[str, object] | None,
) -> tuple[float | None, str]:
    if return_event is None:
        return None, "no_return"
    return_domain = _text(
        return_event.get("clock_domain"),
        "return clock_domain",
    )
    compatible_continuum_domains = {
        "continuum_lifecycle",
        "continuum_pressure",
    }
    domains_are_compatible = (
        return_domain == decision.clock_domain
        or {return_domain, decision.clock_domain} == compatible_continuum_domains
    )
    if not domains_are_compatible:
        return None, "incompatible_clock_domain"
    return_timestamp = _timestamp(
        return_event.get("timestamp"),
        "return timestamp",
    )
    if return_timestamp < decision.timestamp:
        raise ArtifactValidationError("return timestamp precedes decision")
    return return_timestamp - decision.timestamp, "available"


def _analysis_horizon(manifest: dict[str, object]) -> float | None:
    raw_config = manifest.get("config")
    if raw_config is None:
        return None
    config = _mapping(raw_config, "run config")
    raw_horizon = config.get("analysis_horizon_seconds")
    if raw_horizon is None:
        return None
    horizon = _timestamp(raw_horizon, "analysis_horizon_seconds")
    if horizon == 0:
        raise ArtifactValidationError(
            "analysis_horizon_seconds must be greater than zero"
        )
    return horizon


def _return_horizon_result(
    return_event: dict[str, object] | None,
    time_to_return: float | None,
    time_status: str,
    analysis_horizon: float | None,
) -> tuple[bool | None, str]:
    if return_event is None:
        return False, "no_return"
    if analysis_horizon is None:
        return None, "horizon_not_configured"
    if time_status != "available" or time_to_return is None:
        return None, time_status
    return time_to_return <= analysis_horizon, "available"


def _physical_evictions_before_return(
    events: tuple[dict[str, object], ...],
    candidate: DecisionCandidateRow,
    return_event: dict[str, object] | None,
) -> tuple[tuple[int, ...], str]:
    upper_bound = (
        None
        if return_event is None
        else _index(return_event.get("event_index"), "return event_index")
    )
    candidate_blocks = set(candidate.block_ids)
    ambiguous_blocks: set[int] = set()
    matched_indexes: list[int] = []

    for event in events:
        event_index = _index(event.get("event_index"), "event_index")
        if event_index <= candidate.decision_event_index:
            continue
        if upper_bound is not None and event_index >= upper_bound:
            break

        event_type = event.get("event_type")
        if event_type in {"BLOCKS_OBSERVED", "VLLM_PREFIX_SNAPSHOT"}:
            observed = candidate_blocks.intersection(_block_ids(event))
            if observed and (
                event.get("program_id") != candidate.program_id
                or event.get("prefix_id") != candidate.prefix_id
            ):
                ambiguous_blocks.update(observed)
            continue

        if event_type != "BLOCK_EVICTED":
            continue
        payload = _mapping(event.get("payload"), "physical eviction payload")
        block_id = _index(payload.get("block_id"), "physical eviction block_id")
        if block_id in candidate_blocks and block_id not in ambiguous_blocks:
            matched_indexes.append(event_index)

    if ambiguous_blocks:
        return tuple(matched_indexes), "ambiguous_block_reuse"
    if matched_indexes:
        return tuple(matched_indexes), "block_slot_proxy"
    return (), "none_observed"


def build_decision_outcomes_table(
    runs: Iterable[RawRunArtifacts],
) -> tuple[DecisionOutcomeRow, ...]:
    """Build one future-outcome row per decision candidate."""

    raw_runs = tuple(runs)
    tables = build_decision_tables(raw_runs)
    decisions = {
        (row.run_id, row.decision_event_index): row for row in tables.decisions
    }
    runs_by_id = {run.run_id: run for run in raw_runs}
    rows: list[DecisionOutcomeRow] = []

    for candidate in tables.candidates:
        artifacts = runs_by_id[candidate.run_id]
        decision = decisions[(candidate.run_id, candidate.decision_event_index)]
        return_event = _first_future_return(artifacts.events, candidate)
        prefix_event = _return_prefix_snapshot(artifacts.events, return_event)
        time_to_return, time_status = _time_to_return(decision, return_event)
        analysis_horizon = _analysis_horizon(artifacts.manifest)
        returned_within_horizon, horizon_status = _return_horizon_result(
            return_event,
            time_to_return,
            time_status,
            analysis_horizon,
        )
        eviction_indexes, eviction_status = _physical_evictions_before_return(
            artifacts.events,
            candidate,
            return_event,
        )

        return_index: int | None = None
        return_timestamp: float | None = None
        return_domain: str | None = None
        return_request_id: str | None = None
        if return_event is not None:
            return_index = _index(
                return_event.get("event_index"),
                "return event_index",
            )
            return_timestamp = _timestamp(
                return_event.get("timestamp"),
                "return timestamp",
            )
            return_domain = _text(
                return_event.get("clock_domain"),
                "return clock_domain",
            )
            return_request_id = _text(
                return_event.get("request_id"),
                "return request_id",
            )

        prefix_event_index: int | None = None
        same_prefix_reobserved: bool | None = None
        if prefix_event is not None:
            prefix_event_index = _index(
                prefix_event.get("event_index"),
                "return prefix event_index",
            )
            same_prefix_reobserved = prefix_event.get("prefix_id") == candidate.prefix_id

        rows.append(
            DecisionOutcomeRow(
                run_id=candidate.run_id,
                decision_event_index=candidate.decision_event_index,
                program_id=candidate.program_id,
                prefix_id=candidate.prefix_id,
                selected=candidate.selected,
                return_request_id=return_request_id,
                return_arrival_event_index=return_index,
                return_arrival_timestamp=return_timestamp,
                return_arrival_clock_domain=return_domain,
                returned_after_decision=return_event is not None,
                event_distance_to_return=(
                    None
                    if return_index is None
                    else return_index - candidate.decision_event_index
                ),
                time_to_return_seconds=time_to_return,
                time_to_return_status=time_status,
                analysis_horizon_seconds=analysis_horizon,
                returned_within_horizon=returned_within_horizon,
                return_horizon_status=horizon_status,
                return_prefix_snapshot_event_index=prefix_event_index,
                same_prefix_reobserved=same_prefix_reobserved,
                physical_eviction_event_indexes=eviction_indexes,
                physical_eviction_count=len(eviction_indexes),
                physical_eviction_match_status=eviction_status,
            )
        )

    return tuple(rows)
