"""Minimal runtime-neutral Continuum lifecycle coordinator."""

from __future__ import annotations

from .clock import Clock
from .config import ContinuumConfig
from .events import (
    BlockEvicted,
    BlocksObserved,
    FollowupCancelled,
    FollowupWaiting,
    RequestAdmitted,
    RequestArrived,
    ToolGapEnded,
    ToolGapStarted,
    TurnFinished,
)
from .history import (
    CompletedProgramEtaHistory,
    ExternalToolDurationHistory,
    QueueDelayHistory,
    ServerGapHistory,
)
from .retention import RetentionManager
from .snapshots import (
    EvictedRequestQueueDelayRecord,
    PrefixAssociationSnapshot,
    RetentionEntrySnapshot,
    SchedulingCandidate,
    TTLInput,
)
from .ttl import PrefillReloadProvider, estimate_ttl
from .types import (
    ExternalToolDurationRecord,
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    ServerInterRequestGapRecord,
)


class RuntimeCoordinator:
    """Coordinate lifecycle histories and the prefill-to-retention transition."""

    def __init__(
        self,
        *,
        clock: Clock,
        prefill_reload_provider: PrefillReloadProvider,
        default_ttl_seconds: float,
        duration_history_threshold: int,
        queue_delay_window_size: int,
    ) -> None:
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        if not callable(getattr(prefill_reload_provider, "estimate", None)):
            raise TypeError("prefill_reload_provider must provide estimate")
        self._clock = clock
        self.retention = RetentionManager(clock)
        self.server_gap_history = ServerGapHistory()
        self.external_tool_duration_history = ExternalToolDurationHistory()
        self.queue_delay_history = QueueDelayHistory(queue_delay_window_size)
        self.eta_history = CompletedProgramEtaHistory()
        self._prefill_reload_provider = prefill_reload_provider
        self._default_ttl_seconds = default_ttl_seconds
        self._duration_history_threshold = duration_history_threshold
        self._observations: dict[
            tuple[ProgramIdentity, RequestIdentity], PrefixAssociationSnapshot
        ] = {}
        self._prefill_facts: dict[
            tuple[ProgramIdentity, RequestIdentity, PrefixIdentity],
            PrefillContextTokenCountRecord,
        ] = {}
        self._pending_server_gaps: dict[
            ProgramIdentity, tuple[RequestIdentity, float, str | None]
        ] = {}
        self._pending_tool_gaps: dict[ProgramIdentity, tuple[str, float]] = {}
        self._served_turn_counts: dict[ProgramIdentity, int] = {}
        self._request_arrivals: dict[
            RequestIdentity, tuple[ProgramIdentity, float]
        ] = {}
        self._program_first_arrivals: dict[
            ProgramIdentity, tuple[RequestIdentity, float]
        ] = {}

    def scheduler_candidates(
        self, request_ids: tuple[RequestIdentity, ...]
    ) -> tuple[SchedulingCandidate, ...]:
        """Return an immutable scheduler snapshot for the requested IDs.

        Expiry is intentionally performed before protection is read so the
        scheduler consumes the same lazy-expiry state as the retention layer.
        """
        if not isinstance(request_ids, tuple):
            raise TypeError("request_ids must be a tuple")
        for request_id in request_ids:
            if not isinstance(request_id, RequestIdentity):
                raise TypeError("request_ids items must be RequestIdentity")

        self.retention.expire_due()
        snapshot_timestamp = self._clock.now()
        entries = self.retention.planning_snapshots()
        candidates: list[SchedulingCandidate] = []
        for request_id in request_ids:
            try:
                program_id, request_arrival = self._request_arrivals[request_id]
            except KeyError as error:
                raise KeyError(request_id) from error
            try:
                first_request_id, program_arrival = self._program_first_arrivals[program_id]
            except KeyError as error:
                raise KeyError(program_id) from error
            program_entries = tuple(
                entry for entry in entries if entry.program_id == program_id
            )
            protected_entries = tuple(entry for entry in program_entries if entry.protected)
            candidates.append(
                SchedulingCandidate(
                    program_id=program_id,
                    request_id=request_id,
                    program_arrival_timestamp=program_arrival,
                    request_arrival_timestamp=request_arrival,
                    snapshot_timestamp=snapshot_timestamp,
                    turn_index=self._served_turn_counts.get(program_id, 0),
                    is_preempted_waiting=False,
                    is_followup=request_id != first_request_id,
                    program_is_protected=bool(protected_entries),
                    retention_deadline_timestamp=None,
                )
            )
        return tuple(candidates)

    def record_prefill_context_token_count(
        self, fact: PrefillContextTokenCountRecord
    ) -> None:
        if not isinstance(fact, PrefillContextTokenCountRecord):
            raise TypeError(
                "fact must be PrefillContextTokenCountRecord"
            )
        key = (fact.program_id, fact.request_id, fact.prefix_id)
        self._prefill_facts[key] = fact

    def record_queue_delay(
        self, record: EvictedRequestQueueDelayRecord
    ) -> None:
        self.queue_delay_history.record(record)

    def handle(self, event: object) -> None:
        if isinstance(event, RequestArrived):
            self._handle_request_arrived(event)
            return
        if isinstance(event, RequestAdmitted):
            self.retention.admit_followup(event.program_id)
            return
        if isinstance(event, FollowupWaiting):
            self.retention.mark_followup_waiting(event.program_id)
            return
        if isinstance(event, FollowupCancelled):
            self.retention.cancel_followup(event.program_id)
            return
        if isinstance(event, ToolGapStarted):
            self._handle_tool_gap_started(event)
            return
        if isinstance(event, ToolGapEnded):
            self._handle_tool_gap_ended(event)
            return
        if isinstance(event, BlocksObserved):
            self._handle_blocks_observed(event)
            return
        if isinstance(event, TurnFinished):
            self._handle_turn_finished(event)
            return
        if isinstance(event, BlockEvicted):
            self.retention.observe_eviction(event.block_id)
            return
        raise TypeError("unsupported runtime event")

    def _handle_request_arrived(self, event: RequestArrived) -> None:
        previous = self._request_arrivals.get(event.request_id)
        if previous is not None and previous[0] != event.program_id:
            raise ValueError("request identity belongs to another program")
        self._request_arrivals[event.request_id] = (
            event.program_id,
            event.arrival_timestamp,
        )
        self._program_first_arrivals.setdefault(
            event.program_id,
            (event.request_id, event.arrival_timestamp),
        )
        pending = self._pending_server_gaps.pop(event.program_id, None)
        if pending is None:
            return
        previous_request_id, previous_finish_timestamp, tool_type = pending
        self.server_gap_history.record(
            ServerInterRequestGapRecord(
                program_id=event.program_id,
                previous_request_id=previous_request_id,
                next_request_id=event.request_id,
                previous_finish_timestamp=previous_finish_timestamp,
                next_arrival_timestamp=event.arrival_timestamp,
                tool_type=tool_type,
            )
        )

    def _handle_tool_gap_started(self, event: ToolGapStarted) -> None:
        if event.program_id in self._pending_tool_gaps:
            raise ValueError("tool gap already active for program")
        self._pending_tool_gaps[event.program_id] = (
            event.tool_type,
            event.start_timestamp,
        )

    def _handle_tool_gap_ended(self, event: ToolGapEnded) -> None:
        pending = self._pending_tool_gaps.pop(event.program_id, None)
        if pending is None:
            raise ValueError("missing tool gap start")
        tool_type, start_timestamp = pending
        if tool_type != event.tool_type:
            raise ValueError("tool gap type does not match active gap")
        self.external_tool_duration_history.record(
            ExternalToolDurationRecord(
                program_id=event.program_id,
                tool_type=event.tool_type,
                start_timestamp=start_timestamp,
                end_timestamp=event.end_timestamp,
            )
        )

    def _handle_blocks_observed(self, event: BlocksObserved) -> None:
        key = (event.program_id, event.request_id)
        self._observations[key] = PrefixAssociationSnapshot(
            program_id=event.program_id,
            prefix_id=event.prefix_id,
            block_ids=event.block_ids,
            observation_timestamp=event.observation_timestamp,
        )

    def _handle_turn_finished(self, event: TurnFinished) -> None:
        if event.is_terminal:
            self._handle_terminal_turn(event)
            return
        observation = self._observations.get((event.program_id, event.request_id))
        if observation is None:
            raise ValueError("missing BlocksObserved fact")
        fact_key = (event.program_id, event.request_id, observation.prefix_id)
        fact = self._prefill_facts.get(fact_key)
        if fact is None:
            raise ValueError("missing matching prefill token-count fact")

        prefill_reload_seconds, prefill_reload_provenance = (
            self._prefill_reload_provider.estimate(fact.token_count)
        )
        global_server_gap_samples = self.server_gap_history.global_samples()
        tool_server_gap_samples = (
            self.server_gap_history.samples_for_tool(event.next_tool_type)
            if event.next_tool_type is not None
            else ()
        )
        queue_delay_seconds = self.queue_delay_history.mean_seconds()
        eta, eta_provenance = self.eta_history.eta()
        decision = estimate_ttl(
            TTLInput(
                program_id=event.program_id,
                request_id=event.request_id,
                prefix_id=observation.prefix_id,
                decision_timestamp=event.finish_timestamp,
                next_tool_type=event.next_tool_type,
                global_server_gap_samples_seconds=global_server_gap_samples,
                tool_server_gap_samples_seconds=tool_server_gap_samples,
                queue_delay_t_seconds=queue_delay_seconds,
                eta=eta,
                prefill_reload_seconds=prefill_reload_seconds,
                default_ttl_seconds=self._default_ttl_seconds,
                server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
                queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
                eta_provenance=eta_provenance,
                prefill_reload_provenance=prefill_reload_provenance,
                default_ttl_provenance=InputProvenance(
                    InputSource.APPROXIMATED,
                    "configured default TTL",
                ),
            ),
            duration_history_threshold=self._duration_history_threshold,
        )
        self.retention.upsert(
            RetentionEntrySnapshot(
                ttl_decision=decision,
                protected=True,
                waiting_followup=False,
                block_ids=observation.block_ids,
            )
        )
        self._served_turn_counts[event.program_id] = (
            self._served_turn_counts.get(event.program_id, 0) + 1
        )
        self._pending_server_gaps[event.program_id] = (
            event.request_id,
            event.finish_timestamp,
            event.next_tool_type,
        )

    def _handle_terminal_turn(self, event: TurnFinished) -> None:
        turn_count = self._served_turn_counts.get(event.program_id, 0) + 1
        self.eta_history.record_completed_program(event.program_id, turn_count)
        self.retention.complete_program(event.program_id)
        self._pending_server_gaps.pop(event.program_id, None)
        self._pending_tool_gaps.pop(event.program_id, None)
        self._served_turn_counts.pop(event.program_id, None)
        for key in tuple(self._observations):
            if key[0] == event.program_id:
                del self._observations[key]
        for key in tuple(self._prefill_facts):
            if key[0] == event.program_id:
                del self._prefill_facts[key]
        self._program_first_arrivals.pop(event.program_id, None)
        for request_id, (program_id, _arrival_timestamp) in tuple(
            self._request_arrivals.items()
        ):
            if program_id == event.program_id:
                del self._request_arrivals[request_id]


def build_runtime(
    *,
    clock: Clock,
    prefill_reload_provider: PrefillReloadProvider,
    default_ttl_seconds: float,
    duration_history_threshold: int = 100,
    queue_delay_window_size: int | None = None,
) -> RuntimeCoordinator:
    """Build the runtime coordinator with explicit runtime inputs."""
    window_size = (
        ContinuumConfig().queue_delay_window_size
        if queue_delay_window_size is None
        else queue_delay_window_size
    )
    return RuntimeCoordinator(
        clock=clock,
        prefill_reload_provider=prefill_reload_provider,
        default_ttl_seconds=default_ttl_seconds,
        duration_history_threshold=duration_history_threshold,
        queue_delay_window_size=window_size,
    )
