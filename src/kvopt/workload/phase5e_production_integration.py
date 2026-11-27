"""Concrete same-EngineCore integration for Phase 5E Part A.

The integration creates retention state only from terminal Native BlockTable
snapshots.  It never reconstructs a missing hash, timer or owner from the
frozen trace.  G9 is a pre-Pressure snapshot; the actual Pressure event is
bound later to the same state hash and fails closed if that state changed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict

from kvopt.continuum.clock import SystemMonotonicClock
from kvopt.continuum.retention import RetentionManager
from kvopt.continuum.snapshots import (
    RetentionEntrySnapshot,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
)
from kvopt.continuum.types import (
    BlockIdentity,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
)
from kvopt.costaware.a2_native import A2NativeChainSnapshot, A2NativeSnapshotRegistry
from kvopt.costaware.a3_native import A3NativeSelectionCoordinator
from kvopt.costaware.entry_depth import ChainDepthIndex
from kvopt.profiling.experiment_events import (
    ExperimentEvent,
    ExperimentForcedReleaseObserver,
)
from kvopt.runtime.vllm.retention_integration import RetentionRuntimeIntegration

from .phase5_dva_native_provider import DVAERNativeDecisionProvider
from .phase5_replay import canonical_sha256
from .phase5e_a3_retention import (
    PREFILL_MODEL,
    PREFILL_PROFILE_PATH,
    PREFILL_PROFILE_SHA256,
    PREFILL_PROTOCOL_REVISION,
    PREFILL_REVISION,
    SCHEMA_VERSION,
    A3RetentionInputManifest,
    validate_actual_pressure_binding,
)
from .phase5e_native_runtime import Phase5ERuntimeEventSource

_CLOCK_DOMAIN = "continuum_lifecycle"
# Preserve the existing real-runtime cold-start setting used by the shared
# minimal Native integration; this is not a new policy parameter.
_DEFAULT_TTL_SECONDS = 30.0


class Phase5EProductionIntegrationError(RuntimeError):
    """Required live lifecycle or Native identity is unavailable."""


class _SingleForcedReleaseEventCapture:
    """Capture exactly one delegate event before adding live decision identity."""

    def __init__(self) -> None:
        self._event: ExperimentEvent | None = None

    def reset(self) -> None:
        self._event = None

    def emit(self, event: ExperimentEvent) -> None:
        if not isinstance(event, ExperimentEvent):
            raise TypeError("forced-release delegate must emit ExperimentEvent")
        if self._event is not None:
            raise Phase5EProductionIntegrationError(
                "forced-release delegate emitted more than one decision event"
            )
        self._event = event

    def take(self) -> ExperimentEvent:
        if self._event is None:
            raise Phase5EProductionIntegrationError(
                "forced-release delegate did not emit a decision event"
            )
        event = self._event
        self._event = None
        return event


class _BoundForcedReleaseObserver:
    def __init__(self, source: Phase5ERuntimeEventSource) -> None:
        self._source = source
        self._capture = _SingleForcedReleaseEventCapture()
        self._delegate = ExperimentForcedReleaseObserver(self._capture)
        self._context: dict[str, object] | None = None
        self.count = 0

    def begin(self, context: Mapping[str, object]) -> None:
        if self._context is not None:
            raise Phase5EProductionIntegrationError("forced decisions cannot nest")
        self._context = dict(context)

    def end(self) -> None:
        self._context = None

    def observe(self, snapshot: object) -> None:
        if self._context is None:
            raise Phase5EProductionIntegrationError("forced decision lacks boundary")
        event_index = len(self._source.snapshot())
        self._capture.reset()
        self._delegate.observe(snapshot)  # type: ignore[arg-type]
        decision_event = self._capture.take()
        decision_payload = decision_event.payload.to_dict()
        self._source.emit(
            {
                "event_type": decision_event.event_type,
                "timestamp": decision_event.timestamp,
                "clock_domain": decision_event.clock_domain,
                "source": decision_event.source,
                "payload": {
                    **decision_payload,
                    "decision_id": self._context["decision_id"],
                    "frozen_decision_boundary_id": self._context["frozen_decision_boundary_id"],
                },
            }
        )
        selected = tuple(snapshot.selected_releases)  # type: ignore[attr-defined]
        if selected:
            self.count += 1
        self._source.emit(
            {
                "event_type": "FORCED_RELEASE_DECISION_BINDING",
                "payload": {
                    **self._context,
                    "forced_release_event_index": event_index,
                    "selected_release_count": len(selected),
                },
            }
        )


class Phase5EProductionIntegration:
    """Live A3 integration installed on exactly one pinned EngineCore."""

    def __init__(self, event_source: Phase5ERuntimeEventSource) -> None:
        self.event_source = event_source
        self._clock = SystemMonotonicClock()
        self._manager = RetentionManager(self._clock)
        self._registry = A2NativeSnapshotRegistry()
        self._depth = ChainDepthIndex()
        self._observer = _BoundForcedReleaseObserver(event_source)
        self._coordinator = A3NativeSelectionCoordinator(
            self._observer,
            depth_index=self._depth,
            content_registry=self._registry,
            decision_event_index=lambda: len(self.event_source.snapshot()),
            decision_clock_domain=_CLOCK_DOMAIN,
            native_hash_process_id=str(os.getpid()),
        )
        self._delegate = RetentionRuntimeIntegration(
            self._manager,
            self._observer,
            selection_coordinator=self._coordinator,
        )
        self._logical_by_internal: dict[str, str] = {}
        self._program_by_internal: dict[str, ProgramIdentity] = {}
        self._terminal_records: dict[str, dict[str, object]] = {}
        self._active_pressure: dict[str, object] | None = None
        self._pending_plan: dict[str, object] | None = None
        self._g9_manifest: dict[str, object] | None = None
        self._decision_sequence = 0
        self.dva_er_native_decision_provider: DVAERNativeDecisionProvider | None = None
        self._engine_core: object | None = None
        self._block_pool: object | None = None
        self._controller_timers: dict[str, dict[str, object]] = {}
        self._decision_program_session: tuple[str, str] | None = None
        self._all_request_ids: frozenset[str] | None = None
        self._first_wave_request_ids: frozenset[str] | None = None

    def configure_frozen_request_ids(
        self, *, all_request_ids: object, first_wave_request_ids: object
    ) -> None:
        if self._all_request_ids is not None:
            raise Phase5EProductionIntegrationError(
                "frozen request identities are already configured"
            )
        if (
            not isinstance(all_request_ids, (list, tuple))
            or not isinstance(first_wave_request_ids, (list, tuple))
            or len(all_request_ids) != 8
            or len(first_wave_request_ids) != 4
            or len(set(all_request_ids)) != 8
            or len(set(first_wave_request_ids)) != 4
            or not all(isinstance(value, str) and value for value in all_request_ids)
            or not all(isinstance(value, str) and value for value in first_wave_request_ids)
            or not set(first_wave_request_ids) < set(all_request_ids)
        ):
            raise Phase5EProductionIntegrationError(
                "frozen EngineCore request identities are invalid"
            )
        self._all_request_ids = frozenset(all_request_ids)
        self._first_wave_request_ids = frozenset(first_wave_request_ids)

    def bind_request_identity(
        self, *, logical_request_id: str, external_request_id: str, internal_request_id: str
    ) -> None:
        del external_request_id
        if internal_request_id in self._logical_by_internal:
            raise Phase5EProductionIntegrationError("Native request identity is duplicated")
        if self._all_request_ids is not None and logical_request_id not in self._all_request_ids:
            raise Phase5EProductionIntegrationError(
                "EngineCore request is outside the frozen request inventory"
            )
        program_text, separator, _request = logical_request_id.partition(":")
        if not separator or not program_text:
            raise Phase5EProductionIntegrationError("logical request lacks Program identity")
        self._logical_by_internal[internal_request_id] = logical_request_id
        self._program_by_internal[internal_request_id] = ProgramIdentity(program_text)

    def program_for_internal_request(self, request_id: str) -> ProgramIdentity:
        try:
            return self._program_by_internal[request_id]
        except KeyError as error:
            raise Phase5EProductionIntegrationError(
                "terminal request has no bound Program identity"
            ) from error

    def internal_request_id(self, logical_request_id: str) -> str:
        """Resolve a frontend identity only from an observed EngineCore binding."""

        matches = [
            internal_id
            for internal_id, observed in self._logical_by_internal.items()
            if observed == logical_request_id
        ]
        if len(matches) != 1:
            raise Phase5EProductionIntegrationError(
                "logical request does not resolve to one EngineCore request"
            )
        return matches[0]

    def first_wave_prefix_readiness(self) -> Mapping[str, object]:
        """Return exact frozen and observed first-wave identities."""

        expected = self._first_wave_request_ids
        if expected is None:
            expected = frozenset(f"p{index}:r1" for index in range(1, 5))
        observed = {str(record["request_id"]) for record in self._terminal_records.values()}
        return {
            "observed_prefix_count": len(observed),
            "expected_first_wave_request_ids": sorted(expected),
            "observed_first_wave_request_ids": sorted(observed),
            "bound_logical_request_ids": sorted(self._logical_by_internal.values()),
        }

    def observe_terminal_request_snapshot(
        self, snapshot: object, *, observed_at: float, native_hash_process_id: str
    ) -> None:
        internal_id = snapshot.request_id.value
        logical_id = self._logical_by_internal.get(internal_id)
        if logical_id is None:
            raise Phase5EProductionIntegrationError("terminal snapshot is not identity-bound")
        # Only exact frozen first-wave identities create retained prefixes.
        first_wave = self._first_wave_request_ids
        if first_wave is None:
            first_wave = frozenset(f"p{index}:r1" for index in range(1, 5))
        if logical_id not in first_wave:
            return
        blocks = tuple(block for group in snapshot.block_groups for block in group)
        if not blocks or any(block.is_null for block in blocks):
            raise Phase5EProductionIntegrationError("terminal prefix identity is incomplete")
        first_hashless = next(
            (index for index, block in enumerate(blocks) if block.native_hash_hex is None),
            len(blocks),
        )
        hashed_blocks = blocks[:first_hashless]
        hashless_tail = blocks[first_hashless:]
        if (
            not hashed_blocks
            or len(hashless_tail) > 1
            or any(block.native_hash_hex is not None for block in hashless_tail)
        ):
            raise Phase5EProductionIntegrationError(
                "terminal prefix hash identity is not a complete hashed prefix "
                "with at most one hashless tail block"
            )
        block_ids = tuple(block.block_id for block in hashed_blocks)
        native_hashes = tuple(str(block.native_hash_hex) for block in hashed_blocks)
        hashless_tail_block_ids = tuple(block.block_id for block in hashless_tail)
        program = snapshot.program_id
        request = RequestIdentity(logical_id)
        prefix = PrefixIdentity(f"continuum.prefix.native_hash.v1:{native_hashes[-1]}")
        ttl_input = TTLInput(
            program_id=program,
            request_id=request,
            prefix_id=prefix,
            decision_timestamp=observed_at,
            next_tool_type=None,
            global_server_gap_samples_seconds=(),
            tool_server_gap_samples_seconds=(),
            queue_delay_t_seconds=0.0,
            eta=1.0,
            prefill_reload_seconds=0.01,
            default_ttl_seconds=_DEFAULT_TTL_SECONDS,
            server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
            queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
            eta_provenance=InputProvenance(InputSource.APPROXIMATED, "fully memoryful cold start"),
            prefill_reload_provenance=InputProvenance(
                InputSource.APPROXIMATED, "frozen bounded prefill profile"
            ),
            default_ttl_provenance=InputProvenance(
                InputSource.APPROXIMATED, "explicit cold-start TTL"
            ),
        )
        decision = TTLDecision(
            ttl_input=ttl_input,
            ttl_seconds=_DEFAULT_TTL_SECONDS,
            history_mode=TTLHistoryMode.COLD_START,
            reason="no completed tool-gap history in Part A fixture",
        )
        entry = RetentionEntrySnapshot(decision, True, False, tuple(map(BlockIdentity, block_ids)))
        self._manager.upsert(entry)
        chain_id = f"{program.value}:{prefix.canonical_value}"
        self._registry.observe(
            A2NativeChainSnapshot(chain_id, block_ids, native_hashes, native_hash_process_id)
        )
        self._registry.observe_retention_entries((entry,))
        event_index = len(self.event_source.snapshot())
        self._depth.observe_chain(
            (program.value, prefix.canonical_value),
            native_hash_process_id,
            block_ids,
            content_hashes=native_hashes,
            observation_index=event_index,
            observed_at=observed_at,
            clock_domain=_CLOCK_DOMAIN,
        )
        lifecycle_payload = {
            "logical_request_id": logical_id,
            "program_id": program.value,
            "prefix_id": prefix.canonical_value,
            "block_ids": list(block_ids),
            "native_cache_keys": list(native_hashes),
            "excluded_hashless_tail_block_ids": list(hashless_tail_block_ids),
            "hashless_tail_semantics": "NON_RETAINED_PARTIAL_NATIVE_BLOCK",
            "native_hash_process_id": native_hash_process_id,
        }
        self.event_source.emit(
            {
                "event_type": "VLLM_PREFIX_SNAPSHOT",
                "payload": lifecycle_payload,
            }
        )
        self._terminal_records[prefix.canonical_value] = {
            "program_id": program.value,
            "request_id": logical_id,
            "prefix_id": prefix.canonical_value,
            "block_ids": list(block_ids),
            "native_hashes": list(native_hashes),
            "excluded_hashless_tail_block_ids": list(hashless_tail_block_ids),
            "native_hash_process_id": native_hash_process_id,
            "observed_at": observed_at,
            "event_index": event_index,
            "ttl_input": ttl_input,
            "ttl_decision": decision,
        }

    def _state_rows(self, boundary_id: str) -> tuple[list[object], list[object], list[object]]:
        ttl_rows: list[object] = []
        retention_rows: list[object] = []
        chain_rows: list[object] = []
        entries = {
            entry.prefix_id.canonical_value: entry for entry in self._manager.planning_snapshots()
        }
        for prefix_id, record in sorted(self._terminal_records.items()):
            entry = entries.get(prefix_id)
            if entry is None or not entry.protected:
                raise Phase5EProductionIntegrationError("retention evidence is no longer valid")
            ttl_input = asdict(record["ttl_input"])
            ttl_input = _json_safe(ttl_input)
            decision = record["ttl_decision"]
            ttl_decision = {
                "ttl_seconds": decision.ttl_seconds,
                "deadline_timestamp": decision.deadline_timestamp,
                "history_mode": decision.history_mode.value,
                "reason": decision.reason,
            }
            decision_sha = canonical_sha256(ttl_decision)
            shared = {
                "engine_core_identity": self._engine_identity(),
                "decision_boundary_id": boundary_id,
            }
            ttl_rows.append(
                {
                    "program_id": record["program_id"],
                    "request_id": record["request_id"],
                    "prefix_id": prefix_id,
                    **shared,
                    "ttl_input": ttl_input,
                    "ttl_input_sha256": canonical_sha256(ttl_input),
                    "ttl_decision": ttl_decision,
                    "ttl_decision_sha256": decision_sha,
                    "source_event_refs": [f"event:{record['event_index']}"],
                    "source_event_index": record["event_index"],
                    "ttl_clock_domain": _CLOCK_DOMAIN,
                }
            )
            retention_rows.append(
                {
                    "program_id": record["program_id"],
                    "prefix_id": prefix_id,
                    **shared,
                    "protected": entry.protected,
                    "waiting_followup": entry.waiting_followup,
                    "block_ids": record["block_ids"],
                    "ttl_decision_sha256": decision_sha,
                    "created_event_index": record["event_index"],
                }
            )
            content_hashes = [
                canonical_sha256({"native_cache_key": value}) for value in record["native_hashes"]
            ]
            chain_rows.append(
                {
                    "prefix_id": prefix_id,
                    **shared,
                    "block_ids": record["block_ids"],
                    "content_hashes": content_hashes,
                    "native_hash_process_id": record["native_hash_process_id"],
                    "chain_depth_proof_sha256": canonical_sha256(
                        {
                            "prefix_id": prefix_id,
                            "block_ids": record["block_ids"],
                            "native_cache_keys": record["native_hashes"],
                        }
                    ),
                    "observed_event_index": record["event_index"],
                }
            )
        if len(ttl_rows) != 4:
            raise Phase5EProductionIntegrationError("G9 requires four first-wave prefixes")
        return ttl_rows, retention_rows, chain_rows

    def a3_retention_input_manifest(self) -> Mapping[str, object]:
        if self._g9_manifest is not None:
            return dict(self._g9_manifest)
        boundary_id = "phase5e-pressure-01"
        ttl_rows, retention_rows, chain_rows = self._state_rows(boundary_id)
        event_index = len(self.event_source.snapshot())
        timestamp = self._clock.now()
        candidates = [str(row["prefix_id"]) for row in ttl_rows]  # type: ignore[index]
        payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "evidence_scope": "LIVE_NATIVE_PRE_PRESSURE_G9",
            "run_id": "P5E-A-01",
            "decision_id": "phase5e-pre-pressure-g9-1",
            "decision_boundary": {
                "boundary_id": boundary_id,
                "g9_observation_timestamp": timestamp,
                "g9_observation_event_index": event_index,
                "g9_clock_domain": _CLOCK_DOMAIN,
                "pressure_event_status": "NOT_YET_OBSERVED",
                "pressure_observation_timestamp": None,
                "pressure_clock_domain": None,
            },
            "engine_core_identity": {
                "identity": self._engine_identity(),
                "installation_report_sha256": canonical_sha256(
                    self.event_source.installation_report()
                ),
            },
            "a3_candidate_ids": candidates,
            "ttl_inputs": ttl_rows,
            "retention_entries": retention_rows,
            "prefill": {
                "model": PREFILL_MODEL,
                "model_revision": PREFILL_REVISION,
                "tokenizer_revision": PREFILL_REVISION,
                "profile_path": PREFILL_PROFILE_PATH,
                "profile_sha256": PREFILL_PROFILE_SHA256,
                "protocol_revision": PREFILL_PROTOCOL_REVISION,
                "query_token_count": 1984,
                "estimate_seconds": 0.01,
                "provenance": "APPROXIMATED",
            },
            "histories": {
                "server_gap": {
                    "samples": [],
                    "provenance": "EXPLICIT_COLD_START",
                    "reason": "NO_COMPLETED_TOOL_GAPS",
                    "source_event_refs": [],
                },
                "queue_delay": {
                    "value": 0.0,
                    "provenance": "EXPLICIT_COLD_START",
                    "reason": "NO_EVICTED_REQUEST_QUEUE_DELAY",
                    "source_event_refs": [],
                },
                "eta": {
                    "value": 1.0,
                    "provenance": "APPROXIMATED",
                    "reason": "FULLY_MEMORYFUL_COLD_START",
                    "source_event_refs": [],
                },
            },
            "prefix_chain": chain_rows,
            "lifecycle": [
                {
                    "event_type": "VLLM_PREFIX_SNAPSHOT",
                    "event_index": record["event_index"],
                    "timestamp": record["observed_at"],
                    "clock_domain": _CLOCK_DOMAIN,
                    "source_event_sha256": canonical_sha256(
                        ["VLLM_PREFIX_SNAPSHOT", record["event_index"], prefix]
                    ),
                }
                for prefix, record in sorted(self._terminal_records.items())
            ],
            "checks": {
                "required_inputs_complete": True,
                "same_engine_core": True,
                "same_decision_boundary": True,
                "temporal_order_valid": True,
                "no_future_information": True,
                "prefill_profile_hash_valid": True,
                "prefix_block_hash_depth_consistent": True,
                "cold_start_explicit": True,
            },
        }
        payload["runtime_state_sha256"] = canonical_sha256(
            {
                "a3_candidate_ids": candidates,
                "ttl_inputs": ttl_rows,
                "retention_entries": retention_rows,
                "prefix_chain": chain_rows,
            }
        )
        payload["manifest_sha256"] = canonical_sha256(payload)
        A3RetentionInputManifest.from_mapping(payload)
        self._g9_manifest = payload
        self.event_source.emit(
            {
                "event_type": "PHASE5E_G9_PRE_PRESSURE_VALIDATED",
                "payload": {
                    "boundary_id": boundary_id,
                    "g9_manifest_sha256": payload["manifest_sha256"],
                    "runtime_state_sha256": payload["runtime_state_sha256"],
                },
            }
        )
        return dict(payload)

    def begin_pressure_context(
        self, *, boundary_id: str, stage_id: str, pressure_request_id: str
    ) -> None:
        if self._active_pressure is not None:
            raise Phase5EProductionIntegrationError("Pressure contexts cannot nest")
        if self._g9_manifest is None:
            raise Phase5EProductionIntegrationError("Pressure began before G9 validation")
        ttl_rows, retention_rows, chain_rows = self._state_rows(boundary_id)
        state_hash = canonical_sha256(
            {
                "a3_candidate_ids": self._g9_manifest["a3_candidate_ids"],
                "ttl_inputs": ttl_rows,
                "retention_entries": retention_rows,
                "prefix_chain": chain_rows,
            }
        )
        pressure_index = len(self.event_source.snapshot())
        binding = {
            "boundary_id": boundary_id,
            "g9_manifest_sha256": self._g9_manifest["manifest_sha256"],
            "runtime_state_sha256": state_hash,
            "pressure_event_index": pressure_index,
            "pressure_observation_timestamp": self._clock.now(),
            "pressure_clock_domain": _CLOCK_DOMAIN,
        }
        validated_binding = validate_actual_pressure_binding(self._g9_manifest, binding)
        self.event_source.emit(
            {
                "event_type": "PHASE5E_G9_ACTUAL_PRESSURE_BINDING",
                "payload": {
                    **binding,
                    "validation_status": validated_binding["status"],
                },
            }
        )
        self._active_pressure = {
            "boundary_id": boundary_id,
            "stage_id": stage_id,
            "pressure_request_id": pressure_request_id,
        }

    def end_pressure_context(self) -> None:
        if self._active_pressure is None:
            raise Phase5EProductionIntegrationError("Pressure context is not active")
        if self._pending_plan is not None:
            pending = self._pending_plan
            self.event_source.emit(
                {
                    "event_type": "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
                    "payload": {
                        "decision_id": pending["decision_id"],
                        "frozen_decision_boundary_id": pending["frozen_decision_boundary_id"],
                        "matched_physical_block_ids": pending["matched"],
                        "unmatched_physical_block_ids": sorted(pending["expected"]),
                        "hashless_physical_block_ids": pending["hashless"],
                        "status": "PARTIAL_OR_UNMATCHED_PHYSICAL_OUTCOME",
                    },
                }
            )
            self._pending_plan = None
        self._active_pressure = None

    def pressure_context_active(self) -> bool:
        """Report whether the frozen explicit Pressure Boundary is active."""

        return self._active_pressure is not None

    def apply_pressure(self, **kwargs: object):
        if self._active_pressure is None:
            raise Phase5EProductionIntegrationError("Native allocation lacks Pressure context")
        self._decision_sequence += 1
        decision_id = f"phase5e-native-decision-{self._decision_sequence}"
        context = {
            "decision_id": decision_id,
            **self._active_pressure,
            "frozen_decision_boundary_id": self._active_pressure["boundary_id"],
        }
        self._observer.begin(context)
        try:
            result = self._delegate.apply_pressure(**kwargs)
        finally:
            self._observer.end()
        trace = self._coordinator.a3_selection_trace()
        selected = list(result.selected_block_ids)
        self.event_source.emit(
            {
                "event_type": "NATIVE_ENTRY_RELEASE_SELECTION_PLAN",
                "payload": {
                    **context,
                    "selected_native_block_ids": selected,
                    "a3_selection_trace": list(trace),
                    "predicted_native_victim_sequences_by_entry": [
                        {"entry": row.get("key"), "audits": row.get("audits", ())} for row in trace
                    ],
                },
            }
        )
        self._pending_plan = {
            "decision_id": decision_id,
            "frozen_decision_boundary_id": context["frozen_decision_boundary_id"],
            "selected": tuple(selected),
        }
        return result

    def observe_native_selection_returned(
        self, selected: tuple[tuple[int, str | None], ...]
    ) -> None:
        if self._pending_plan is None:
            raise Phase5EProductionIntegrationError("Native selection lacks a plan")
        if tuple(row[0] for row in selected) != self._pending_plan["selected"]:
            raise Phase5EProductionIntegrationError("Native selection differs from plan")
        self._pending_plan["expected"] = {
            block_id for block_id, value in selected if value is not None
        }
        self._pending_plan["hashless"] = [block_id for block_id, value in selected if value is None]
        self._pending_plan["matched"] = []

    def observe_native_eviction(self, block_id: BlockIdentity) -> None:
        self._delegate.observe_native_eviction(block_id)
        self._registry.observe_eviction(block_id.block_id)
        if self._pending_plan is None or "expected" not in self._pending_plan:
            return
        expected = self._pending_plan["expected"]
        if block_id.block_id in expected:
            expected.remove(block_id.block_id)
            self._pending_plan["matched"].append(block_id.block_id)

    def build_dva_er_native_decision_provider(
        self,
        *,
        engine_core: object,
        scheduler: object,
        kv_cache_manager: object,
        block_pool: object,
    ) -> DVAERNativeDecisionProvider:
        del scheduler, kv_cache_manager
        self._engine_core = engine_core
        self._block_pool = block_pool
        identity = self._engine_identity()
        return DVAERNativeDecisionProvider(
            engine_core_identity=identity,
            engine_core=engine_core,
            block_pool_reader=lambda: self._read_block_pool(identity),
            candidate_reader=lambda: self._read_candidates(identity),
            timer_reader=lambda decision_timestamp: self._read_timers(identity, decision_timestamp),
        )

    def bind_dva_decision_identity(self, *, program_id: str, session_id: str) -> None:
        """Bind the current decision without reading a future trace row."""

        if not program_id or not session_id:
            raise Phase5EProductionIntegrationError(
                "DVA decision Program/Session identity is required"
            )
        self._decision_program_session = (program_id, session_id)

    def observe_controller_timer_armed(
        self,
        *,
        candidate_id: str,
        chain_id: str,
        program_id: str,
        session_id: str,
        armed_at_timestamp: float,
        expires_at_timestamp: float,
        source_event_index: int,
        clock_domain: str,
    ) -> None:
        """Record a timer only when the controller actually arms it."""

        now = self._clock.now()
        if (
            not candidate_id
            or not chain_id
            or not program_id
            or not session_id
            or source_event_index < 0
            or clock_domain != _CLOCK_DOMAIN
            or armed_at_timestamp > now
            or expires_at_timestamp < now
            or expires_at_timestamp < armed_at_timestamp
        ):
            raise Phase5EProductionIntegrationError(
                "Controller-Armed Timer evidence is invalid or from the future"
            )
        self._controller_timers[candidate_id] = {
            "chain_id": chain_id,
            "program_id": program_id,
            "session_id": session_id,
            "armed_at_timestamp": armed_at_timestamp,
            "expires_at_timestamp": expires_at_timestamp,
            "source_event_index": source_event_index,
            "clock_domain": clock_domain,
            "pending_tool_gap_source": "CONTROLLER_ARMED_TIMER",
        }
        self.event_source.emit(
            {
                "event_type": "CONTROLLER_ARMED_TIMER",
                "payload": {
                    "candidate_id": candidate_id,
                    **self._controller_timers[candidate_id],
                },
            }
        )

    def _engine_identity(self) -> str:
        if self._engine_core is None:
            return "phase5e-engine-core-installing"
        return f"engine-core:{id(self._engine_core)}"

    def _read_block_pool(self, identity: str) -> Mapping[str, object]:
        if self._block_pool is None:
            raise Phase5EProductionIntegrationError("live BlockPool is unavailable")
        queue = getattr(self._block_pool, "free_block_queue", None)
        head = getattr(queue, "fake_free_list_head", None)
        tail = getattr(queue, "fake_free_list_tail", None)
        current = getattr(head, "next_free_block", None)
        blocks = []
        order = []
        rank = 0
        while current is not None and current is not tail:
            block_id = int(current.block_id)
            owners = [
                entry.program_id.value
                for entry in self._manager.planning_snapshots()
                if BlockIdentity(block_id) in entry.block_ids
            ]
            blocks.append(
                {
                    "block_id": block_id,
                    "has_hash": getattr(current, "block_hash", None) is not None,
                    "refcount": int(current.ref_cnt),
                    "native_lru_rank": rank,
                    "owner_candidate_ids": owners,
                    "protected_candidate_ids": owners if owners else [],
                }
            )
            order.append(block_id)
            current = current.next_free_block
            rank += 1
        return {
            "engine_core_identity": identity,
            "observed_at_timestamp": self._clock.now(),
            "source": "LIVE_VLLM_BLOCK_POOL",
            "blocks": blocks,
            "free_queue_order": order,
        }

    def _read_candidates(self, identity: str) -> Mapping[str, object]:
        entries = self._manager.planning_snapshots()
        legal = [entry.program_id.value for entry in entries]
        if len(legal) != len(set(legal)):
            raise Phase5EProductionIntegrationError("candidate Program identities are not unique")
        if self._decision_program_session is None:
            raise Phase5EProductionIntegrationError(
                "DVA decision Program/Session identity is not bound"
            )
        decision_program, decision_session = self._decision_program_session
        return {
            "engine_core_identity": identity,
            "observed_at_timestamp": self._clock.now(),
            "source": "LIVE_RETENTION_MANAGER",
            "legal_candidate_ids": legal,
            "candidate_key_by_id": {
                row.program_id.value: row.prefix_id.canonical_value for row in entries
            },
            "candidate_program_session_by_id": {
                row.program_id.value: {
                    "program_id": row.program_id.value,
                    "session_id": row.program_id.value,
                }
                for row in entries
            },
            "decision_program_id": decision_program,
            "decision_session_id": decision_session,
            "a0_order": legal,
            "a0_baseline_selection": legal[0] if legal else None,
            "a1_features": {},
            "a3_features": {},
        }

    def _read_timers(self, identity: str, decision_timestamp: float) -> Mapping[str, object]:
        observed = self._clock.now()
        followups = {
            candidate_id: {
                **timer,
                "observed_at_timestamp": observed,
                "pending_tool_gap_seconds": float(timer["expires_at_timestamp"])
                - decision_timestamp,
            }
            for candidate_id, timer in self._controller_timers.items()
            if float(timer["expires_at_timestamp"]) >= observed
        }
        return {
            "engine_core_identity": identity,
            "observed_at_timestamp": observed,
            "source": "CONTROLLER_ARMED_TIMER",
            "followups": followups,
        }


def _json_safe(value: object) -> object:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def build_phase5e_production_integration(
    event_source: Phase5ERuntimeEventSource,
) -> Phase5EProductionIntegration:
    """Factory referenced by the single-shot Native runner."""

    return Phase5EProductionIntegration(event_source)
