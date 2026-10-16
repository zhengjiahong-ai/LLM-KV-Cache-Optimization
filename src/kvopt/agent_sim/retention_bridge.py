"""Bridge between the Phase 2F simulator and the frozen Continuum runtime.

Nothing in ``kvopt.continuum`` is modified or reimplemented: this module only
*drives* the frozen components (``RuntimeCoordinator``, ``RetentionManager``,
``RetentionAwareSelectionCoordinator``) with simulator events and reads their
decisions back.

Provenance discipline:

* tool-gap histories are recorded from trace-declared gaps (workload input,
  classified ``OBSERVED`` by the frozen record types);
* ``queue_delay_t_seconds`` degenerates to ``0.0`` because the simulator has no
  queueing model (documented limitation; see simulator design §5);
* ``prefill_reload_seconds`` comes from the frozen offline profile artifact
  (``APPROXIMATED``), with an explicit, separately-flagged linear extrapolation
  beyond the frozen 512-token grid;
* a mirror of the server-gap samples is kept so the report can run the frozen
  TTL estimator under sensitivity sweeps without fabricating observations.
"""

from __future__ import annotations

from dataclasses import dataclass

from kvopt.continuum.clock import FakeClock
from kvopt.continuum.config import ContinuumConfig
from kvopt.continuum.events import (
    BlockEvicted,
    BlocksObserved,
    FollowupCancelled,
    FollowupWaiting,
    ProgramCompleted,
    ProgramStarted,
    RequestAdmitted,
    RequestArrived,
    ToolGapEnded,
    ToolGapStarted,
    TurnFinished,
)
from kvopt.continuum.prefill_profile import (
    TOKEN_GRID,
    load_prefill_reload_provider,
)
from kvopt.continuum.pressure import RetentionAwareSelectionCoordinator
from kvopt.continuum.runtime import build_runtime
from kvopt.continuum.selection import (
    EligibilityPreparation,
    RetentionEntryKey,
)
from kvopt.continuum.ttl import compute_default_ttl_seconds
from kvopt.continuum.types import (
    BlockIdentity,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
)
from kvopt.profiling.forced_release import (
    ForcedReleaseObserver,
    NullForcedReleaseObserver,
)

PREFILL_PROFILE_PATH = (
    "docs/experiments/phase1b-continuum/artifacts/"
    "prefill-reload-profile-formal-20260920T045859Z-6183d106.json"
)


class ExtrapolatingPrefillProvider:
    """Frozen profile lookup plus an explicitly-flagged linear extrapolation.

    The frozen provider raises outside the 16..512 token grid. Long agent
    sessions exceed it, so the simulator either extrapolates from the last two
    grid points (``extrapolate=True``, ``APPROXIMATED`` provenance) or censors
    at the 512-token value (sensitivity variant).
    """

    def __init__(self, inner, *, extrapolate: bool) -> None:
        self._inner = inner
        self._extrapolate = extrapolate
        self._low_tokens = TOKEN_GRID[-2]
        self._low_seconds = inner.estimate(self._low_tokens)[0]
        self._high_tokens = TOKEN_GRID[-1]
        self._high_seconds = inner.estimate(self._high_tokens)[0]
        self._slope = (self._high_seconds - self._low_seconds) / (
            self._high_tokens - self._low_tokens
        )

    def estimate(self, token_count: int) -> tuple[float, InputProvenance]:
        try:
            return self._inner.estimate(token_count)
        except ValueError:
            pass
        if not self._extrapolate:
            return self._high_seconds, InputProvenance(
                InputSource.APPROXIMATED,
                "prefill reload censored at frozen profile grid maximum (512 tokens)",
            )
        seconds = self._high_seconds + self._slope * (token_count - self._high_tokens)
        return seconds, InputProvenance(
            InputSource.APPROXIMATED,
            "linear extrapolation beyond frozen PrefillReload profile grid",
        )


@dataclass(frozen=True, slots=True)
class TTLProbeRecord:
    """One TTL decision captured for the sensitivity probe."""

    request_id: str
    next_tool_type: str | None
    global_samples: tuple[float, ...]
    tool_samples: tuple[float, ...]
    eta: float
    prefill_reload_seconds: float
    chosen_ttl_seconds: float
    history_mode: str


@dataclass(frozen=True, slots=True)
class EligibilityOutcome:
    """Result of one retention-aware eligibility preparation."""

    preparation: EligibilityPreparation
    release_keys: tuple[RetentionEntryKey, ...]
    natural_expiry_keys: tuple[RetentionEntryKey, ...]


class RetentionBridge:
    """Drives the frozen Continuum runtime from simulator events."""

    def __init__(
        self,
        *,
        clock: FakeClock,
        extrapolate_prefill_profile: bool,
        forced_release_observer: ForcedReleaseObserver | None = None,
        profile_path: str = PREFILL_PROFILE_PATH,
    ) -> None:
        inner = load_prefill_reload_provider(profile_path)
        provider = ExtrapolatingPrefillProvider(
            inner, extrapolate=extrapolate_prefill_profile
        )
        default_ttl = compute_default_ttl_seconds(provider.estimate(256)[0])
        self.provider = provider
        self.default_ttl_seconds = default_ttl
        self.runtime = build_runtime(
            clock=clock,
            prefill_reload_provider=provider,
            default_ttl_seconds=default_ttl,
            duration_history_threshold=ContinuumConfig().duration_history_threshold,
            queue_delay_window_size=ContinuumConfig().queue_delay_window_size,
        )
        self.manager = self.runtime.retention
        self.coordinator = RetentionAwareSelectionCoordinator(
            forced_release_observer
            if forced_release_observer is not None
            else NullForcedReleaseObserver()
        )
        # Mirror of the server-gap samples (same records, same order) so the
        # report can re-run the frozen TTL estimator under sensitivity sweeps.
        # The frozen runtime keeps pending gaps per program; the mirror must
        # too, otherwise interleaved programs mis-attribute each other's gaps.
        self._gap_mirror: list[tuple[str | None, float]] = []
        self._pending_gap: dict[str, tuple[float, str | None]] = {}
        self.ttl_probe_records: list[TTLProbeRecord] = []
        self.natural_expiry_count = 0
        self.forced_release_count = 0
        self.zero_marginal_release_count = 0

    # ------------------------------------------------------------------
    # lifecycle event forwarding
    # ------------------------------------------------------------------
    def program_started(self, program_id: str, timestamp: float) -> None:
        self.runtime.handle(
            ProgramStarted(ProgramIdentity(program_id), timestamp)
        )

    def program_completed(self, program_id: str, timestamp: float) -> None:
        self.runtime.handle(
            ProgramCompleted(ProgramIdentity(program_id), timestamp)
        )

    def request_arrived(
        self, program_id: str, request_id: str, timestamp: float
    ) -> None:
        self.runtime.handle(
            RequestArrived(
                ProgramIdentity(program_id), RequestIdentity(request_id), timestamp
            )
        )
        pending = self._pending_gap.pop(program_id, None)
        if pending is not None:
            finish_timestamp, tool_type = pending
            self._gap_mirror.append((tool_type, timestamp - finish_timestamp))

    def request_admitted(self, program_id: str, request_id: str, timestamp: float) -> None:
        self.runtime.handle(
            RequestAdmitted(
                ProgramIdentity(program_id), RequestIdentity(request_id), timestamp
            )
        )

    def followup_waiting(self, program_id: str, request_id: str, timestamp: float) -> None:
        self.runtime.handle(
            FollowupWaiting(
                ProgramIdentity(program_id), RequestIdentity(request_id), timestamp
            )
        )

    def followup_cancelled(self, program_id: str, request_id: str, timestamp: float) -> None:
        self.runtime.handle(
            FollowupCancelled(
                ProgramIdentity(program_id), RequestIdentity(request_id), timestamp
            )
        )

    def tool_gap_started(self, program_id: str, tool_type: str, timestamp: float) -> None:
        self.runtime.handle(
            ToolGapStarted(ProgramIdentity(program_id), tool_type, timestamp)
        )

    def tool_gap_ended(self, program_id: str, tool_type: str, timestamp: float) -> None:
        self.runtime.handle(
            ToolGapEnded(ProgramIdentity(program_id), tool_type, timestamp)
        )

    def blocks_observed(
        self,
        program_id: str,
        request_id: str,
        prefix_id: str,
        block_ids: tuple[int, ...],
        timestamp: float,
    ) -> None:
        self.runtime.handle(
            BlocksObserved(
                ProgramIdentity(program_id),
                RequestIdentity(request_id),
                PrefixIdentity(prefix_id),
                tuple(BlockIdentity(block_id) for block_id in block_ids),
                timestamp,
            )
        )

    def block_evicted(self, block_id: int, timestamp: float) -> None:
        self.runtime.handle(BlockEvicted(BlockIdentity(block_id), timestamp))

    def record_prefill_tokens(
        self, program_id: str, request_id: str, prefix_id: str, token_count: int
    ) -> None:
        from kvopt.continuum.types import PrefillContextTokenCountRecord

        self.runtime.record_prefill_context_token_count(
            PrefillContextTokenCountRecord(
                program_id=ProgramIdentity(program_id),
                request_id=RequestIdentity(request_id),
                prefix_id=PrefixIdentity(prefix_id),
                token_count=token_count,
                provenance=InputProvenance(
                    InputSource.EXTERNAL, "simulation workload trace prompt tokens"
                ),
            )
        )

    def turn_finished(
        self,
        *,
        program_id: str,
        request_id: str,
        timestamp: float,
        is_terminal: bool,
        next_tool_type: str | None,
    ) -> None:
        global_samples = tuple(
            duration for _tool, duration in self._gap_mirror
        )
        tool_samples = tuple(
            duration
            for tool, duration in self._gap_mirror
            if next_tool_type is not None and tool == next_tool_type
        )
        eta, _provenance = self.runtime.eta_history.eta()
        self.runtime.handle(
            TurnFinished(
                ProgramIdentity(program_id),
                RequestIdentity(request_id),
                timestamp,
                is_terminal,
                next_tool_type,
            )
        )
        entry = self.manager.snapshot(
            RetentionEntryKey(
                ProgramIdentity(program_id), PrefixIdentity(f"phase2f:{request_id}")
            )
        )
        if entry is not None:
            self.ttl_probe_records.append(
                TTLProbeRecord(
                    request_id=request_id,
                    next_tool_type=next_tool_type,
                    global_samples=global_samples,
                    tool_samples=tool_samples,
                    eta=eta,
                    prefill_reload_seconds=entry.ttl_decision.ttl_input.prefill_reload_seconds,
                    chosen_ttl_seconds=entry.ttl_decision.ttl_seconds,
                    history_mode=entry.ttl_decision.history_mode.value,
                )
            )
        # Only non-terminal turns open a server gap, exactly as the frozen
        # runtime does (``_handle_turn_finished`` sets the pending gap only on
        # the non-terminal path).
        if not is_terminal:
            self._pending_gap[program_id] = (timestamp, next_tool_type)

    # ------------------------------------------------------------------
    # lazy expiry and pressure eligibility
    # ------------------------------------------------------------------
    def expire_due_and_count(self) -> int:
        """Frozen lazy expiry; returns how many entries flipped to unprotected."""
        before = {
            (entry.program_id, entry.prefix_id): entry.protected
            for entry in self.manager.planning_snapshots()
        }
        self.manager.expire_due()
        expired = 0
        for entry in self.manager.planning_snapshots():
            key = (entry.program_id, entry.prefix_id)
            if before.get(key, False) and not entry.protected:
                expired += 1
        self.natural_expiry_count += expired
        return expired

    def prepare_eligibility(
        self, candidates, *, required_blocks: int, timestamp: float
    ) -> EligibilityOutcome:
        """Frozen eligibility + pressure-release planning (read-only)."""
        preparation = self.coordinator.prepare(
            candidates,
            self.manager.planning_snapshots(),
            required_blocks=required_blocks,
            timestamp=timestamp,
        )
        release_keys = preparation.ordinary_expired_entries + tuple(
            effect.entry_key for effect in preparation.pressure_releases
        )
        self.forced_release_count += len(preparation.pressure_releases)
        self.zero_marginal_release_count += sum(
            1
            for effect in preparation.pressure_releases
            if not effect.newly_eligible_block_ids
        )
        return EligibilityOutcome(
            preparation=preparation,
            release_keys=release_keys,
            natural_expiry_keys=preparation.ordinary_expired_entries,
        )

    def commit_releases(self, keys) -> None:
        self.manager.commit_pressure_releases(tuple(keys))
