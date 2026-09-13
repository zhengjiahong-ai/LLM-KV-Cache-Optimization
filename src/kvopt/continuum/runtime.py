"""Minimal runtime-neutral Continuum lifecycle coordinator."""

from __future__ import annotations

from .clock import Clock
from .events import BlocksObserved, TurnFinished
from .retention import RetentionManager
from .snapshots import (
    PrefixAssociationSnapshot,
    RetentionEntrySnapshot,
    TTLInput,
)
from .ttl import PrefillReloadProvider, estimate_ttl
from .types import (
    InputProvenance,
    InputSource,
    PrefillContextTokenCountRecord,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
)


class RuntimeCoordinator:
    """Coordinate only the C4 prefill-to-retention transition."""

    def __init__(
        self,
        *,
        clock: Clock,
        prefill_reload_provider: PrefillReloadProvider,
        default_ttl_seconds: float,
        duration_history_threshold: int,
    ) -> None:
        if not isinstance(clock, Clock):
            raise TypeError("clock must implement Clock")
        if not callable(getattr(prefill_reload_provider, "estimate", None)):
            raise TypeError("prefill_reload_provider must provide estimate")
        self.retention = RetentionManager(clock)
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

    def record_prefill_context_token_count(
        self, fact: PrefillContextTokenCountRecord
    ) -> None:
        if not isinstance(fact, PrefillContextTokenCountRecord):
            raise TypeError(
                "fact must be PrefillContextTokenCountRecord"
            )
        key = (fact.program_id, fact.request_id, fact.prefix_id)
        self._prefill_facts[key] = fact

    def handle(self, event: object) -> None:
        if isinstance(event, BlocksObserved):
            self._handle_blocks_observed(event)
            return
        if isinstance(event, TurnFinished):
            self._handle_turn_finished(event)
            return
        raise TypeError("unsupported C4 runtime event")

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
            raise ValueError("terminal turns are outside the C4 runtime scope")
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
        decision = estimate_ttl(
            TTLInput(
                program_id=event.program_id,
                request_id=event.request_id,
                prefix_id=observation.prefix_id,
                decision_timestamp=event.finish_timestamp,
                next_tool_type=event.next_tool_type,
                global_server_gap_samples_seconds=(),
                tool_server_gap_samples_seconds=(),
                queue_delay_t_seconds=0.0,
                eta=1.0,
                prefill_reload_seconds=prefill_reload_seconds,
                default_ttl_seconds=self._default_ttl_seconds,
                server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
                queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
                eta_provenance=InputProvenance(
                    InputSource.APPROXIMATED,
                    "FULLY_MEMORYFUL_COLD_START",
                ),
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


def build_runtime(
    *,
    clock: Clock,
    prefill_reload_provider: PrefillReloadProvider,
    default_ttl_seconds: float,
    duration_history_threshold: int = 100,
) -> RuntimeCoordinator:
    """Build the minimal C4 coordinator with explicit runtime inputs."""
    return RuntimeCoordinator(
        clock=clock,
        prefill_reload_provider=prefill_reload_provider,
        default_ttl_seconds=default_ttl_seconds,
        duration_history_threshold=duration_history_threshold,
    )
