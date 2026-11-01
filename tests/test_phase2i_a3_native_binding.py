import os
from dataclasses import dataclass
from types import SimpleNamespace

from kvopt.continuum import FakeClock, RetentionMode
from kvopt.continuum.retention import RetentionManager
from kvopt.costaware.a2_native import A2NativeChainSnapshot, A2NativeSnapshotRegistry
from kvopt.profiling.experiment_events import InMemoryExperimentEventSink
from kvopt.runtime.vllm.observer import NativeHashedEvictionObservation
from scripts.spikes.phase2_minimal_observability_metal import (
    _CountingForcedReleaseObserver,
    _IndexedEventSink,
    _ObservedRetentionIntegration,
)


@dataclass(frozen=True, slots=True)
class _Block:
    block_id: int
    ref_cnt: int = 0
    block_hash: object = object()


class _ForcedSelectionDelegate:
    def __init__(self, observer: _CountingForcedReleaseObserver) -> None:
        self._observer = observer

    def apply_pressure(self, **kwargs):
        self._observer.count += 1
        selected = tuple(block.block_id for block in kwargs["blocks"])
        kwargs["remove_selected"](selected)
        return SimpleNamespace(selected_block_ids=selected)


def _integration():
    clock = FakeClock()
    sink = InMemoryExperimentEventSink()
    indexed = _IndexedEventSink(sink)
    observer = _CountingForcedReleaseObserver(indexed, indexed)
    registry = A2NativeSnapshotRegistry()
    process = str(os.getpid())
    registry.observe(
        A2NativeChainSnapshot(
            chain_id="program:prefix",
            block_ids=(1, 2),
            content_hashes=("content-1", "content-2"),
            native_hash_process_id=process,
        )
    )
    runtime = SimpleNamespace(retention=RetentionManager(clock))
    integration = _ObservedRetentionIntegration(
        runtime,
        clock,
        observer,
        phase2g_release_policy="A0",
        phase2g_a2_registry=registry,
        event_index=indexed,
        sink=indexed,
        clock_domain="continuum_pressure",
    )
    integration._delegate = _ForcedSelectionDelegate(observer)
    return integration, sink


def test_late_physical_eviction_consumes_unique_pending_plan_content_match() -> None:
    integration, _sink = _integration()
    integration.begin_pressure_context(
        boundary_id="pressure:40",
        stage_id="round-40",
        pressure_request_id="pressure-request-1",
    )
    result = integration.apply_pressure(
        mode=RetentionMode.CONTROLLED,
        blocks=(_Block(1), _Block(2)),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=lambda _ids: None,
    )
    assert result.selected_block_ids == (1, 2)

    # This callback is deliberately after apply_pressure() returned, matching
    # the real FreeKVCacheBlockQueue -> BlockPool lifecycle.
    integration.observe_native_selection_returned(
        ((1, "content-1"), (2, "content-2"))
    )
    attribution = integration.match_physical_eviction(
        NativeHashedEvictionObservation(1, "content-1", 0, True)
    )
    assert attribution["physical_attribution"] == (
        "MATCHED_PENDING_SELECTION_PLAN"
    )
    assert attribution["decision_id"] == "native-entry-release-1"

    integration.end_pressure_context()
    later = integration.match_physical_eviction(
        NativeHashedEvictionObservation(2, "content-2", 0, True)
    )
    assert later["physical_attribution"] == "UNATTRIBUTED"


def test_entry_release_without_hashed_native_victim_is_explicitly_observed() -> None:
    integration, sink = _integration()
    integration.begin_request_context(("program:turn:40", "program-b:turn:40"))
    integration.apply_pressure(
        mode=RetentionMode.CONTROLLED,
        blocks=(_Block(1), _Block(2)),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=lambda _ids: None,
    )
    integration.observe_native_selection_returned(((1, None), (2, None)))
    integration.end_execution_context()

    outcomes = tuple(
        event
        for event in sink.snapshot()
        if event.event_type == "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME"
    )
    assert len(outcomes) == 1
    assert outcomes[0].payload["status"] == "NO_PHYSICAL_EVICTION_OBSERVED"
    assert outcomes[0].payload["boundary_type"] == "NATIVE_DRAIN_BATCH"


def test_pure_native_allocation_attempt_never_creates_entry_pending_plan() -> None:
    integration, sink = _integration()
    integration._forced_release_observer.count = 0
    integration._delegate = SimpleNamespace(
        apply_pressure=lambda **kwargs: SimpleNamespace(
            selected_block_ids=tuple(block.block_id for block in kwargs["blocks"])
        )
    )
    integration.begin_pressure_context(
        boundary_id="pressure:40",
        stage_id="round-40",
        pressure_request_id="pressure-request-1",
    )
    integration.apply_pressure(
        mode=RetentionMode.CONTROLLED,
        blocks=(_Block(1), _Block(2)),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=lambda _ids: None,
    )
    integration.observe_native_selection_returned(((99, "unrelated"),))
    integration.end_pressure_context()

    event_types = tuple(event.event_type for event in sink.snapshot())
    assert "NATIVE_ALLOCATION_ATTEMPT" in event_types
    assert "NATIVE_ENTRY_RELEASE_SELECTION_PLAN" not in event_types
    assert "NATIVE_SELECTION_PLAN_PENDING" not in event_types
    assert "NATIVE_ENTRY_RELEASE_PHYSICAL_OUTCOME" not in event_types


def test_wrong_block_or_content_never_inherits_pending_pressure_decision() -> None:
    integration, _sink = _integration()
    integration.begin_pressure_context(
        boundary_id="pressure:40",
        stage_id="round-40",
        pressure_request_id="pressure-request-1",
    )
    integration.apply_pressure(
        mode=RetentionMode.CONTROLLED,
        blocks=(_Block(1), _Block(2)),
        required_blocks=2,
        timestamp=1.0,
        remove_selected=lambda _ids: None,
    )
    integration.observe_native_selection_returned(
        ((1, "content-1"), (2, "content-2"))
    )

    wrong_block = integration.match_physical_eviction(
        NativeHashedEvictionObservation(99, "content-1", 0, True)
    )
    wrong_content = integration.match_physical_eviction(
        NativeHashedEvictionObservation(1, "recycled-content", 0, True)
    )
    assert wrong_block["physical_attribution"] == "UNATTRIBUTED"
    assert wrong_content["physical_attribution"] == "UNATTRIBUTED"
