from __future__ import annotations

from types import SimpleNamespace

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
from kvopt.workload.phase5_dva_native_selection import DVAERNativeSelectionCoordinator


def _entry(program: str, block: int) -> RetentionEntrySnapshot:
    observed = InputProvenance(InputSource.OBSERVED)
    approximated = InputProvenance(InputSource.APPROXIMATED, "test")
    ttl_input = TTLInput(
        program_id=ProgramIdentity(program),
        request_id=RequestIdentity(f"request:{program}"),
        prefix_id=PrefixIdentity(f"prefix:{program}"),
        decision_timestamp=0.0,
        next_tool_type="bash",
        global_server_gap_samples_seconds=(1.0,),
        tool_server_gap_samples_seconds=(1.0,),
        queue_delay_t_seconds=0.0,
        prefill_reload_seconds=1.0,
        eta=1.0,
        default_ttl_seconds=100.0,
        server_gap_history_provenance=observed,
        queue_delay_provenance=observed,
        eta_provenance=observed,
        prefill_reload_provenance=approximated,
        default_ttl_provenance=approximated,
    )
    return RetentionEntrySnapshot(
        block_ids=(BlockIdentity(block),),
        waiting_followup=True,
        protected=True,
        ttl_decision=TTLDecision(
            ttl_input=ttl_input,
            ttl_seconds=100.0,
            history_mode=TTLHistoryMode.TOOL_SPECIFIC,
        ),
    )


def test_live_dva_coordinator_uses_snapshot_selection() -> None:
    observed = {}

    def evaluate(**kwargs: object):
        observed.update(kwargs)
        return {"selected_candidate_id": "p2", "scores": {"p1": 1, "p2": 0}}

    coordinator = DVAERNativeSelectionCoordinator(None, snapshot_evaluator=evaluate)
    preparation = coordinator.prepare(
        [
            SimpleNamespace(block_id=1, has_block_hash=True, lru_rank=0),
            SimpleNamespace(block_id=2, has_block_hash=True, lru_rank=1),
        ],
        [_entry("p1", 1), _entry("p2", 2)],
        required_blocks=1,
        timestamp=1.0,
    )
    assert preparation.pressure_releases[0].entry_key.program_id.value == "p2"
    assert len(observed["legal_candidate_keys"]) == 2
    assert coordinator.selection_trace()[0]["selected_candidate_id"] == "p2"
