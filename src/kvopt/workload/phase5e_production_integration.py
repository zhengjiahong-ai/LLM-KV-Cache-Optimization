"""Concrete same-EngineCore integration for Phase 5E Part A.

The integration creates retention state only from terminal Native BlockTable
snapshots.  It never reconstructs a missing hash, timer or owner from the
frozen trace.  G9 is a pre-Pressure snapshot; the actual Pressure event is
bound later to the same state hash and fails closed if that state changed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path

from kvopt.continuum.clock import SystemMonotonicClock
from kvopt.continuum.pressure import RetentionAwareSelectionCoordinator
from kvopt.continuum.retention import RetentionManager
from kvopt.continuum.selection import RetentionEntryKey
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
from kvopt.costaware.a1_native import A1NativeSelectionCoordinator
from kvopt.costaware.a2_native import A2NativeChainSnapshot, A2NativeSnapshotRegistry
from kvopt.costaware.a3_native import A3NativeSelectionCoordinator
from kvopt.costaware.entry_depth import ChainDepthIndex
from kvopt.profiling.experiment_events import (
    ExperimentEvent,
    ExperimentForcedReleaseObserver,
)
from kvopt.runtime.vllm.retention_integration import RetentionRuntimeIntegration

from .phase5_dva_candidate_adapter import DVAERCandidateAdapter
from .phase5_dva_native_provider import DVAERNativeDecisionProvider
from .phase5_dva_native_selection import DVAERNativeSelectionCoordinator
from .phase5_replay import canonical_sha256
from .phase5_system_runtime import SYSTEM_RUNTIME_CONTRACTS
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
_DVA_CPU_GATE_SHA256 = "4a0ac1c25e78b16425ab99adfab77b98b9ae4f6e24422d94eee5e8079e68d323"


def _dva_cpu_gate() -> Mapping[str, object]:
    path = Path(__file__).parents[3] / "docs/experiments/dva-er-v1-cpu-gate.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _DVA_CPU_GATE_SHA256:
        raise Phase5EProductionIntegrationError("DVA-ER CPU gate identity differs")
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise Phase5EProductionIntegrationError("DVA-ER CPU gate is malformed")
    return value
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
    """Live project policy integration installed on exactly one EngineCore."""

    def __init__(
        self,
        event_source: Phase5ERuntimeEventSource,
        *,
        system_id: str = "A3_SUFFIX",
        execution_role: str = "PART_A_CONFORMANCE",
    ) -> None:
        if system_id not in {
            "NATIVE",
            "CONTINUUM_ADAPTED",
            "A1_ORIGINAL",
            "A3_SUFFIX",
            "DVA_ER_V1",
        }:
            raise Phase5EProductionIntegrationError(
                "system lacks an installed project-side Native policy"
            )
        if execution_role not in {"PART_A_CONFORMANCE", "SWE_CALIBRATION"}:
            raise Phase5EProductionIntegrationError("execution role is unsupported")
        self.system_id = system_id
        self.execution_role = execution_role
        self.policy_id = str(SYSTEM_RUNTIME_CONTRACTS[system_id]["policy_id"])
        self.event_source = event_source
        self._clock = SystemMonotonicClock()
        self._manager = RetentionManager(self._clock)
        self._registry = A2NativeSnapshotRegistry()
        self._depth = ChainDepthIndex()
        self._observer = _BoundForcedReleaseObserver(event_source)
        if system_id == "A3_SUFFIX":
            self._coordinator: RetentionAwareSelectionCoordinator | None = (
                A3NativeSelectionCoordinator(
                    self._observer,
                    depth_index=self._depth,
                    content_registry=self._registry,
                    decision_event_index=lambda: len(self.event_source.snapshot()),
                    decision_clock_domain=_CLOCK_DOMAIN,
                    native_hash_process_id=str(os.getpid()),
                )
            )
        elif system_id == "A1_ORIGINAL":
            self._coordinator = A1NativeSelectionCoordinator(self._observer)
        elif system_id == "CONTINUUM_ADAPTED":
            self._coordinator = RetentionAwareSelectionCoordinator(self._observer)
        elif system_id == "DVA_ER_V1":
            self._dva_adapter = DVAERCandidateAdapter(cpu_gate=_dva_cpu_gate())
            self._coordinator = DVAERNativeSelectionCoordinator(
                self._observer,
                snapshot_evaluator=self._evaluate_dva_snapshot,
            )
        else:
            self._dva_adapter = None
            self._coordinator = None
        if system_id != "DVA_ER_V1":
            self._dva_adapter = None
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
        self._dva_decision_metadata: dict[str, str] | None = None
        self._dva_live_context: dict[str, object] | None = None
        self._all_request_ids: frozenset[str] | None = None
        self._first_wave_request_ids: frozenset[str] | None = None
        self._calibration_group_id: str | None = None
        self._session_by_program: dict[str, str] = {}
        self._trace_sha256_by_program: dict[str, str] = {}

    def configure_frozen_request_ids(
        self, *, all_request_ids: object, first_wave_request_ids: object
    ) -> None:
        if self._all_request_ids is not None:
            raise Phase5EProductionIntegrationError(
                "frozen request identities are already configured"
            )
        expected_all_count = 8 if self.execution_role == "PART_A_CONFORMANCE" else None
        expected_first_count = 4 if self.execution_role == "PART_A_CONFORMANCE" else None
        if (
            not isinstance(all_request_ids, (list, tuple))
            or not isinstance(first_wave_request_ids, (list, tuple))
            or not all_request_ids
            or (expected_all_count is not None and len(all_request_ids) != expected_all_count)
            or (
                expected_first_count is not None
                and len(first_wave_request_ids) != expected_first_count
            )
            or len(set(all_request_ids)) != len(all_request_ids)
            or len(set(first_wave_request_ids)) != len(first_wave_request_ids)
            or not all(isinstance(value, str) and value for value in all_request_ids)
            or not all(isinstance(value, str) and value for value in first_wave_request_ids)
            or not set(first_wave_request_ids).issubset(set(all_request_ids))
            or (
                self.execution_role == "PART_A_CONFORMANCE"
                and set(first_wave_request_ids) == set(all_request_ids)
            )
        ):
            raise Phase5EProductionIntegrationError(
                "frozen EngineCore request identities are invalid"
            )
        self._all_request_ids = frozenset(all_request_ids)
        self._first_wave_request_ids = frozenset(first_wave_request_ids)

    def configure_calibration_identities(
        self,
        *,
        group_id: object,
        session_by_program: object,
        trace_sha256_by_program: object,
    ) -> None:
        if self.execution_role != "SWE_CALIBRATION":
            raise Phase5EProductionIntegrationError(
                "Calibration identities cannot be installed in Part A"
            )
        if self._calibration_group_id is not None:
            raise Phase5EProductionIntegrationError(
                "Calibration identities are already configured"
            )
        if not isinstance(group_id, str) or not group_id:
            raise Phase5EProductionIntegrationError("Calibration Group identity is missing")
        if not isinstance(session_by_program, Mapping) or not isinstance(
            trace_sha256_by_program, Mapping
        ):
            raise Phase5EProductionIntegrationError(
                "Calibration Program identity maps are malformed"
            )
        sessions = {str(key): str(value) for key, value in session_by_program.items()}
        traces = {str(key): str(value) for key, value in trace_sha256_by_program.items()}
        if (
            not sessions
            or set(sessions) != set(traces)
            or any(not key or not value for key, value in sessions.items())
            or any(len(value) != 64 for value in traces.values())
        ):
            raise Phase5EProductionIntegrationError(
                "Calibration Program identity maps are incomplete"
            )
        self._calibration_group_id = group_id
        self._session_by_program = sessions
        self._trace_sha256_by_program = traces

    def bind_request_identity(
        self, *, logical_request_id: str, external_request_id: str, internal_request_id: str
    ) -> None:
        del external_request_id
        if internal_request_id in self._logical_by_internal:
            raise Phase5EProductionIntegrationError("Native request identity is duplicated")
        if self._all_request_ids is not None and logical_request_id not in self._all_request_ids:
            raise Phase5EProductionIntegrationError(
                "EngineCore request is outside the frozen request inventory: "
                f"logical_request_id={logical_request_id!r}, "
                f"frozen_request_ids={tuple(sorted(self._all_request_ids))!r}"
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

    def logical_for_internal_request(self, request_id: str) -> str:
        try:
            return self._logical_by_internal[request_id]
        except KeyError as error:
            raise Phase5EProductionIntegrationError(
                "Native request has no bound logical identity"
            ) from error

    def bind_dva_allocation_request(self, internal_request_id: str) -> None:
        """Bind DVA identity from the request currently allocating Native KV."""

        if self.system_id != "DVA_ER_V1":
            return
        logical = self._logical_by_internal.get(internal_request_id)
        program = self._program_by_internal.get(internal_request_id)
        if (
            logical is None
            or program is None
            or self._calibration_group_id is None
            or program.value not in self._session_by_program
            or program.value not in self._trace_sha256_by_program
        ):
            raise Phase5EProductionIntegrationError(
                "DVA allocating request lacks frozen Program/Session lineage"
            )
        self.bind_dva_decision_identity(
            program_id=program.value,
            session_id=self._session_by_program[program.value],
            group_id=self._calibration_group_id,
            turn_id=logical,
            trace_sha256=self._trace_sha256_by_program[program.value],
        )

    def internal_request_id(self, logical_request_id: str) -> str:
        """Resolve a frontend identity only from an observed EngineCore binding."""

        value = self.try_internal_request_id(logical_request_id)
        if value is None:
            raise Phase5EProductionIntegrationError(
                "logical request does not resolve to one EngineCore request"
            )
        return value

    def try_internal_request_id(self, logical_request_id: str) -> str | None:
        """Return None only while a frozen request has not reached EngineCore."""

        matches = [
            internal_id
            for internal_id, observed in self._logical_by_internal.items()
            if observed == logical_request_id
        ]
        if not matches:
            return None
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
        self,
        snapshot: object,
        *,
        observed_at: float,
        native_hash_process_id: str,
        native_hash_block_size: int,
    ) -> None:
        internal_id = snapshot.request_id.value
        logical_id = self._logical_by_internal.get(internal_id)
        if logical_id is None:
            raise Phase5EProductionIntegrationError("terminal snapshot is not identity-bound")
        # Part A deliberately retains only its frozen first wave. Calibration
        # is a trace-driven multi-turn replay: every frozen request may become
        # a predecessor of a later Turn and must therefore register its real
        # terminal prefix.  The two roles must not share the Part A shortcut.
        first_wave = self._first_wave_request_ids
        if first_wave is None:
            first_wave = frozenset(f"p{index}:r1" for index in range(1, 5))
        retained_request_ids = (
            self._all_request_ids
            if self.execution_role == "SWE_CALIBRATION"
            else first_wave
        )
        if retained_request_ids is None or logical_id not in retained_request_ids:
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
        native_block_hashes = tuple(
            str(block.native_hash_hex) for block in hashed_blocks
        )
        native_hashes: tuple[str, ...] = tuple(
            value
            if len(value) == 64
            else value[:64]
            if (
                len(value) == 72
                and block.cache_group_id == 0
                and value[64:] == "00000000"
            )
            else ""
            for block, value in zip(hashed_blocks, native_block_hashes, strict=True)
        )
        if any(len(value) != 64 for value in native_hashes):
            raise Phase5EProductionIntegrationError(
                "terminal prefix Native content hash encoding is unsupported"
            )
        if (
            isinstance(native_hash_block_size, bool)
            or not isinstance(native_hash_block_size, int)
            or native_hash_block_size <= 0
        ):
            raise Phase5EProductionIntegrationError(
                "terminal prefix Native block size is incomplete"
            )
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
            "ordered_native_hashes": list(native_hashes),
            "ordered_native_block_hashes": list(native_block_hashes),
            "native_block_hash_encoding": "SHA256_CBOR_BYTES_PLUS_UINT32_CACHE_GROUP_ID",
            "hash_num_tokens": len(native_hashes) * native_hash_block_size,
            "native_hash_block_size": native_hash_block_size,
            "native_hash_function": "SHA256_CBOR_BYTES",
            "excluded_hashless_tail_block_ids": list(hashless_tail_block_ids),
            "hashless_tail_semantics": "NON_RETAINED_PARTIAL_NATIVE_BLOCK",
            "native_hash_process_id": native_hash_process_id,
        }
        self.event_source.emit(
            {
                "event_type": "VLLM_PREFIX_SNAPSHOT",
                "request_id": logical_id,
                "program_id": program.value,
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
                for prefix, record in sorted(
                    self._terminal_records.items(),
                    key=lambda item: int(item[1]["event_index"]),
                )
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
        self.finalize_pending_physical_outcome()
        self._active_pressure = None

    def finalize_pending_physical_outcome(self) -> None:
        """Seal the current decision after Native eviction callbacks have run."""

        if self._pending_plan is None:
            return
        pending = self._pending_plan
        expected = set(pending.get("expected", ()))
        matched = list(pending.get("matched", ()))
        hashless = list(pending.get("hashless", ()))
        self.event_source.emit(
            {
                "event_type": "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME",
                "payload": {
                    "decision_id": pending["decision_id"],
                    "frozen_decision_boundary_id": pending[
                        "frozen_decision_boundary_id"
                    ],
                    "matched_physical_block_ids": matched,
                    "unmatched_physical_block_ids": sorted(expected),
                    "hashless_physical_block_ids": hashless,
                    "status": (
                        "COMPLETE_PHYSICAL_OUTCOME"
                        if not expected
                        else "PARTIAL_OR_UNMATCHED_PHYSICAL_OUTCOME"
                    ),
                },
            }
        )
        self._pending_plan = None

    def pressure_context_active(self) -> bool:
        """Report whether the frozen explicit Pressure Boundary is active."""

        if self.execution_role == "SWE_CALIBRATION":
            return self.system_id != "NATIVE"
        return self._active_pressure is not None

    def apply_pressure(self, **kwargs: object):
        generated_context = False
        if self._active_pressure is None:
            if self.execution_role != "SWE_CALIBRATION":
                raise Phase5EProductionIntegrationError(
                    "Native allocation lacks Pressure context"
                )
            self.finalize_pending_physical_outcome()
            generated_context = True
            boundary_id = f"phase5-calibration-pressure-{self._decision_sequence + 1}"
            self._active_pressure = {
                "boundary_id": boundary_id,
                "stage_id": "NATIVE_CACHE_ALLOCATION",
                "pressure_request_id": "ENGINE_CORE_SCHEDULER",
            }
            self.event_source.emit(
                {
                    "event_type": "PHASE5_CALIBRATION_NATIVE_PRESSURE_BOUNDARY",
                    "payload": {
                        **self._active_pressure,
                        "system_id": self.system_id,
                        "policy_id": self.policy_id,
                        "pressure_observation_timestamp": self._clock.now(),
                        "pressure_clock_domain": _CLOCK_DOMAIN,
                    },
                }
            )
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
            if generated_context:
                self._active_pressure = None
        trace_reader = getattr(self._coordinator, "selection_trace", None)
        trace = tuple(trace_reader()) if callable(trace_reader) else ()
        selected = list(result.selected_block_ids)
        self.event_source.emit(
            {
                "event_type": "NATIVE_ENTRY_RELEASE_SELECTION_PLAN",
                "payload": {
                    **context,
                    "system_id": self.system_id,
                    "policy_id": self.policy_id,
                    "selected_native_block_ids": selected,
                    "selection_trace": list(trace),
                    "a3_selection_trace": (
                        list(trace) if self.system_id == "A3_SUFFIX" else []
                    ),
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
        if not self._pending_plan["expected"]:
            self.finalize_pending_physical_outcome()

    def observe_native_eviction(self, block_id: BlockIdentity) -> None:
        self._delegate.observe_native_eviction(block_id)
        self._registry.observe_eviction(block_id.block_id)
        if self._pending_plan is None or "expected" not in self._pending_plan:
            return
        expected = self._pending_plan["expected"]
        if block_id.block_id in expected:
            expected.remove(block_id.block_id)
            self._pending_plan["matched"].append(block_id.block_id)
            if not expected:
                self.finalize_pending_physical_outcome()

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

    def bind_dva_decision_identity(
        self,
        *,
        program_id: str,
        session_id: str,
        group_id: str | None = None,
        turn_id: str | None = None,
        trace_sha256: str | None = None,
    ) -> None:
        """Bind the current decision without reading a future trace row."""

        if not program_id or not session_id:
            raise Phase5EProductionIntegrationError(
                "DVA decision Program/Session identity is required"
            )
        self._decision_program_session = (program_id, session_id)
        if group_id is not None or turn_id is not None or trace_sha256 is not None:
            if (
                not group_id
                or not turn_id
                or not isinstance(trace_sha256, str)
                or len(trace_sha256) != 64
            ):
                raise Phase5EProductionIntegrationError(
                    "DVA decision metadata is incomplete"
                )
            self._dva_decision_metadata = {
                "group_id": group_id,
                "turn_id": turn_id,
                "trace_sha256": trace_sha256,
            }

    def _evaluate_dva_snapshot(
        self,
        *,
        legal_candidate_keys: tuple[RetentionEntryKey, ...],
        released_candidate_keys: frozenset[RetentionEntryKey],
        a0_order: tuple[RetentionEntryKey, ...],
        required_blocks: int,
        decision_timestamp: float,
    ) -> Mapping[str, object]:
        if (
            self.dva_er_native_decision_provider is None
            or self._dva_adapter is None
            or self._decision_program_session is None
            or self._dva_decision_metadata is None
        ):
            raise Phase5EProductionIntegrationError(
                "DVA live selector lacks provider or decision identity"
            )
        self._decision_sequence += 1
        self._dva_live_context = {
            "legal_candidate_keys": legal_candidate_keys,
            "released_candidate_keys": released_candidate_keys,
            "a0_order": a0_order,
            "decision_timestamp": decision_timestamp,
        }
        program_id, session_id = self._decision_program_session
        metadata = self._dva_decision_metadata
        try:
            snapshot = self.dva_er_native_decision_provider.build_snapshot(
                decision_id=f"dva-er:{self._decision_sequence}",
                group_id=metadata["group_id"],
                stratum="SWE_BENCH",
                program_id=program_id,
                session_id=session_id,
                turn_id=metadata["turn_id"],
                trace_sha256=metadata["trace_sha256"],
                decision_timestamp=decision_timestamp,
                required_blocks=required_blocks,
                h_seconds=60.0,
            )
            decision = self._dva_adapter.evaluate(snapshot)
            return {
                "selected_candidate_id": decision.selected_candidate_id,
                "scores": dict(decision.scores),
                "ordered_candidate_ids": list(decision.ordered_candidate_ids),
                "simulated_native_victim_sequences": {
                    key: list(value)
                    for key, value in decision.simulated_native_victim_sequences.items()
                },
                "snapshot_sha256": decision.snapshot_sha256,
                "branch": decision.branch,
            }
        finally:
            self._dva_live_context = None

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

    def observe_controller_timer_command(
        self,
        *,
        candidate_id: str,
        chain_id: str,
        program_id: str,
        session_id: str,
        timeout_seconds: float,
        predecessor_request_id: str,
        successor_request_id: str,
        source: str,
        source_event_index: int,
    ) -> None:
        """Arm a timer when EngineCore receives a live controller command.

        The frontend transmits only identities already observed by the
        controller and its configured timeout. Both timestamps are sampled in
        the EngineCore clock domain, so no frontend timestamp or future replay
        arrival is imported into the decision state.
        """

        if (
            not predecessor_request_id
            or not successor_request_id
            or source != "OBSERVED_PREDECESSOR_TERMINAL_PLUS_FROZEN_TOOL_GAP"
            or
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) < 0.0
        ):
            raise Phase5EProductionIntegrationError(
                "Controller timer command is invalid or not terminal-armed"
            )
        armed = self._clock.now()
        self.observe_controller_timer_armed(
            candidate_id=candidate_id,
            chain_id=chain_id,
            program_id=program_id,
            session_id=session_id,
            armed_at_timestamp=armed,
            expires_at_timestamp=armed + float(timeout_seconds),
            source_event_index=source_event_index,
            clock_domain=_CLOCK_DOMAIN,
        )
        self._controller_timers[candidate_id].update(
            {
                "predecessor_request_id": predecessor_request_id,
                "successor_request_id": successor_request_id,
                "controller_command_source": source,
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
        context = self._dva_live_context
        legal = (
            None
            if context is None
            else {
                key.program_id.value
                for key in context["legal_candidate_keys"]
            }
        )
        observed_at = (
            self._clock.now()
            if context is None
            else float(context["decision_timestamp"])
        )
        blocks_by_id: dict[int, dict[str, object]] = {}
        order = []
        rank = 0
        while current is not None and current is not tail:
            block_id = int(current.block_id)
            owners = [
                entry.program_id.value
                for entry in self._manager.planning_snapshots()
                if BlockIdentity(block_id) in entry.block_ids
                and (legal is None or entry.program_id.value in legal)
            ]
            blocks_by_id[block_id] = {
                "block_id": block_id,
                "has_hash": getattr(current, "block_hash", None) is not None,
                "refcount": int(current.ref_cnt),
                "native_lru_rank": rank,
                "owner_candidate_ids": owners,
                "protected_candidate_ids": owners if owners else [],
            }
            order.append(block_id)
            current = current.next_free_block
            rank += 1
        all_blocks = getattr(self._block_pool, "blocks", None)
        if not isinstance(all_blocks, list):
            raise Phase5EProductionIntegrationError("complete live BlockPool is unavailable")
        for block in all_blocks:
            block_id = int(block.block_id)
            if getattr(block, "is_null", False) or block_id in blocks_by_id:
                continue
            owners = [
                entry.program_id.value
                for entry in self._manager.planning_snapshots()
                if BlockIdentity(block_id) in entry.block_ids
                and (legal is None or entry.program_id.value in legal)
            ]
            blocks_by_id[block_id] = {
                "block_id": block_id,
                "has_hash": getattr(block, "block_hash", None) is not None,
                "refcount": int(block.ref_cnt),
                "native_lru_rank": rank,
                "owner_candidate_ids": owners,
                "protected_candidate_ids": owners if owners else [],
            }
            rank += 1
        return {
            "engine_core_identity": identity,
            "observed_at_timestamp": observed_at,
            "source": "LIVE_VLLM_BLOCK_POOL",
            "blocks": [blocks_by_id[key] for key in sorted(blocks_by_id)],
            "free_queue_order": order,
        }

    def _read_candidates(self, identity: str) -> Mapping[str, object]:
        context = self._dva_live_context
        if context is None:
            raise Phase5EProductionIntegrationError("DVA live candidate context is unavailable")
        legal_keys = tuple(context["legal_candidate_keys"])
        by_key = {
            RetentionEntryKey(row.program_id, row.prefix_id): row
            for row in self._manager.planning_snapshots()
        }
        entries = tuple(by_key[key] for key in legal_keys)
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
            "observed_at_timestamp": float(context["decision_timestamp"]),
            "source": "LIVE_RETENTION_MANAGER",
            "legal_candidate_ids": legal,
            "candidate_key_by_id": {
                row.program_id.value: row.prefix_id.canonical_value for row in entries
            },
            "candidate_program_session_by_id": {
                row.program_id.value: {
                    "program_id": row.program_id.value,
                    "session_id": self._controller_timers[row.program_id.value][
                        "session_id"
                    ],
                }
                for row in entries
            },
            "decision_program_id": decision_program,
            "decision_session_id": decision_session,
            "a0_order": [key.program_id.value for key in context["a0_order"]],
            "a0_baseline_selection": context["a0_order"][0].program_id.value,
            "a1_features": {},
            "a3_features": {},
        }

    def _read_timers(self, identity: str, decision_timestamp: float) -> Mapping[str, object]:
        context = self._dva_live_context
        if context is None:
            raise Phase5EProductionIntegrationError("DVA timer context is unavailable")
        observed = decision_timestamp
        legal = {
            key.program_id.value for key in context["legal_candidate_keys"]
        }
        followups = {
            candidate_id: {
                **timer,
                "observed_at_timestamp": observed,
                "pending_tool_gap_seconds": float(timer["expires_at_timestamp"])
                - decision_timestamp,
            }
            for candidate_id, timer in self._controller_timers.items()
            if candidate_id in legal and float(timer["expires_at_timestamp"]) >= observed
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


def build_phase5_calibration_production_integration(
    event_source: Phase5ERuntimeEventSource,
    *,
    system_id: str,
) -> Phase5EProductionIntegration:
    """Build an exact project-side Calibration policy without fallback."""

    return Phase5EProductionIntegration(
        event_source,
        system_id=system_id,
        execution_role="SWE_CALIBRATION",
    )
