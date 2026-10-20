from kvopt.continuum import (
    BlockIdentity,
    InputProvenance,
    InputSource,
    PrefixIdentity,
    ProgramIdentity,
    RequestIdentity,
    RetentionEntrySnapshot,
    TTLDecision,
    TTLHistoryMode,
    TTLInput,
)
from kvopt.costaware.a2_contract import BlockDecisionInput, DecisionRequest
from kvopt.costaware.a2_geometry import Membership
from kvopt.costaware.a2_native import (
    A2NativeBlockAdapter,
    A2NativeChainSnapshot,
    A2NativeSnapshotRegistry,
)
from kvopt.runtime.vllm.types import EvictionCandidate, EvictionContext


def _candidate(block_id: int, rank: int) -> EvictionCandidate:
    return EvictionCandidate(block_id, 0, True, rank)


def _context(need: int = 1) -> EvictionContext:
    return EvictionContext(need, 0, 4, 10.0)


def _entry(program: str, prefix: str, blocks: tuple[int, ...]) -> RetentionEntrySnapshot:
    ttl_input = TTLInput(
        program_id=ProgramIdentity(program),
        request_id=RequestIdentity(f"{program}-request"),
        prefix_id=PrefixIdentity(prefix),
        decision_timestamp=0.0,
        next_tool_type=None,
        global_server_gap_samples_seconds=(),
        tool_server_gap_samples_seconds=(),
        queue_delay_t_seconds=0.0,
        eta=1.0,
        prefill_reload_seconds=1.0,
        default_ttl_seconds=20.0,
        server_gap_history_provenance=InputProvenance(InputSource.OBSERVED),
        queue_delay_provenance=InputProvenance(InputSource.OBSERVED),
        eta_provenance=InputProvenance(InputSource.APPROXIMATED, "test"),
        prefill_reload_provenance=InputProvenance(InputSource.APPROXIMATED, "test"),
        default_ttl_provenance=InputProvenance(InputSource.APPROXIMATED, "test"),
    )
    decision = TTLDecision(
        ttl_input,
        20.0,
        TTLHistoryMode.COLD_START,
        "test",
    )
    return RetentionEntrySnapshot(
        decision,
        True,
        True,
        tuple(BlockIdentity(block) for block in blocks),
    )


def _request(
    candidates: list[EvictionCandidate],
    context: EvictionContext,
    *,
    weights: dict[str, float] | None = None,
) -> DecisionRequest:
    memberships = {
        1: (Membership("cold", 2, "h-cold-2"),),
        2: (Membership("hot", 2, "h-hot-2"),),
    }
    return DecisionRequest(
        required_blocks=context.required_blocks,
        timestamp=context.timestamp,
        blocks=tuple(
            BlockDecisionInput(
                candidate.block_id,
                candidate.lru_rank,
                candidate.has_block_hash,
                memberships[candidate.block_id],
            )
            for candidate in candidates
        ),
        chain_length={"cold": 2, "hot": 2},
        reuse_weight=weights or {"cold": 0.9, "hot": 0.1},
    )


def test_a2_native_adapter_can_diverge_on_same_legal_set_and_count() -> None:
    candidates = [_candidate(1, 0), _candidate(2, 1)]
    context = _context()
    adapter = A2NativeBlockAdapter(_request)

    selected = adapter.select_victims(candidates, context)

    assert selected == [2]
    assert adapter.last_audit is not None
    assert adapter.last_audit.native_lru_victims == (1,)
    assert adapter.last_audit.legal_block_ids == (1, 2)
    assert adapter.last_audit.required_blocks == 1
    assert adapter.last_audit.chain_count == 2
    assert adapter.last_audit.shared_block_count == 0
    assert adapter.last_audit.identified_hashed_block_count == 2
    assert adapter.last_audit.legal_content_hashes == ((1, None), (2, None))
    assert not adapter.last_audit.used_fallback


def test_a2_native_adapter_negative_control_agrees_with_lru() -> None:
    candidates = [_candidate(1, 0), _candidate(2, 1)]
    context = _context()

    def factory(candidates, context):
        return _request(candidates, context, weights={"cold": 0.1, "hot": 0.9})

    adapter = A2NativeBlockAdapter(factory)
    assert adapter.select_victims(candidates, context) == [1]
    assert adapter.last_audit is not None
    assert adapter.last_audit.selected_victims == adapter.last_audit.native_lru_victims


def test_a2_native_adapter_missing_weight_falls_back_to_lru() -> None:
    candidates = [_candidate(1, 0), _candidate(2, 1)]
    context = _context()

    def factory(candidates, context):
        request = _request(candidates, context)
        return DecisionRequest(
            request.required_blocks,
            request.timestamp,
            request.blocks,
            request.chain_length,
            {"cold": 0.9},
        )

    adapter = A2NativeBlockAdapter(factory)
    assert adapter.select_victims(candidates, context) == [1]
    assert adapter.last_audit is not None
    assert adapter.last_audit.used_fallback
    assert adapter.last_audit.fallbacks == ("reuse_weight_missing",)


def test_a2_native_adapter_stale_or_missing_identity_falls_back() -> None:
    candidates = [_candidate(1, 0), _candidate(2, 1)]
    context = _context()

    def factory(candidates, context):
        request = _request(candidates, context)
        blocks = (
            BlockDecisionInput(1, 0, True, ()),
            request.blocks[1],
        )
        return DecisionRequest(
            request.required_blocks,
            request.timestamp,
            blocks,
            request.chain_length,
            request.reuse_weight,
        )

    adapter = A2NativeBlockAdapter(factory)
    assert adapter.select_victims(candidates, context) == [1]
    assert adapter.last_audit is not None
    assert adapter.last_audit.fallbacks == ("content_unverified",)


def test_a2_native_adapter_factory_failure_is_safe_and_audited() -> None:
    candidates = [_candidate(1, 0), _candidate(2, 1)]
    context = _context()

    def broken(_candidates, _context):
        raise RuntimeError("stale snapshot")

    adapter = A2NativeBlockAdapter(broken)
    assert adapter.select_victims(candidates, context) == [1]
    assert adapter.last_audit is not None
    assert adapter.last_audit.used_fallback
    assert adapter.last_audit.adapter_problems == (
        "request_factory_failed:RuntimeError:stale snapshot",
    )


def test_a2_native_adapter_rejects_changed_legal_set_without_scoring() -> None:
    candidates = [_candidate(1, 0), _candidate(2, 1)]
    context = _context()

    def changed(_candidates, context):
        return DecisionRequest(
            context.required_blocks,
            context.timestamp,
            (BlockDecisionInput(2, 1, True, (Membership("hot", 2, "h"),)),),
            {"hot": 2},
            {"hot": 0.1},
        )

    adapter = A2NativeBlockAdapter(changed)
    assert adapter.select_victims(candidates, context) == [1]
    assert adapter.last_audit is not None
    assert adapter.last_audit.adapter_problems == (
        "request blocks do not match the live legal candidate snapshot",
    )


def test_registry_builds_depth_and_all_shared_chain_memberships() -> None:
    registry = A2NativeSnapshotRegistry()
    registry.observe(A2NativeChainSnapshot("a:pa", (1, 2), ("h1", "h2"), "p"))
    registry.observe(A2NativeChainSnapshot("b:pb", (1, 3), ("h1", "h3"), "p"))
    candidates = [
        EvictionCandidate(1, 0, True, 0, "h1"),
        EvictionCandidate(2, 0, True, 1, "h2"),
        EvictionCandidate(3, 0, True, 2, "h3"),
    ]

    request = registry.build_request(
        candidates,
        _context(2),
        (_entry("a", "pa", (1, 2)), _entry("b", "pb", (1, 3))),
        tau_seconds=30.0,
    )

    assert request.blocks[0].memberships == (
        Membership("a:pa", 1, "h1"),
        Membership("b:pb", 1, "h1"),
    )
    assert request.chain_length == {"a:pa": 2, "b:pb": 2}
    assert set(request.reuse_weight) == {"a:pa", "b:pb"}

    adapter = A2NativeBlockAdapter(lambda _candidates, _context: request)
    adapter.select_victims(candidates, _context(2))
    assert adapter.last_audit is not None
    assert adapter.last_audit.chain_count == 2
    assert adapter.last_audit.shared_block_count == 1
    assert adapter.last_audit.identified_hashed_block_count == 3


def test_registry_rejects_slot_reuse_after_eviction() -> None:
    registry = A2NativeSnapshotRegistry()
    registry.observe(A2NativeChainSnapshot("a:pa", (1,), ("old" ,), "p"))
    registry.observe_eviction(1)
    candidates = [EvictionCandidate(1, 0, True, 0, "new")]

    request = registry.build_request(
        candidates,
        _context(),
        (_entry("a", "pa", (1,)),),
        tau_seconds=30.0,
    )

    assert request.blocks[0].memberships == ()
    adapter = A2NativeBlockAdapter(lambda _candidates, _context: request)
    assert adapter.select_victims(candidates, _context()) == [1]
    assert adapter.last_audit is not None
    assert adapter.last_audit.fallbacks == ("content_unverified",)


def test_registry_partial_eviction_preserves_chain_and_prefix_boundary() -> None:
    registry = A2NativeSnapshotRegistry()
    registry.observe(
        A2NativeChainSnapshot("a:pa", (1, 2, 3), ("h1", "h2", "h3"), "p")
    )

    registry.observe_eviction(2, content_hash="h2", native_hash_process_id="p")

    state = registry.chain_state("a:pa")
    assert state is not None
    assert state.snapshot.block_ids == (1, 2, 3)
    assert state.resident_depths == (1, 3)
    assert state.reusable_prefix_blocks == 1
    assert registry.content_identity(1) is not None
    assert registry.content_identity(2) is None
    assert registry.content_identity(3) is not None

    request = registry.build_request(
        [
            EvictionCandidate(1, 0, True, 0, "h1"),
            EvictionCandidate(3, 0, True, 1, "h3"),
        ],
        _context(),
        (_entry("a", "pa", (1, 2, 3)),),
        tau_seconds=30.0,
    )
    assert request.chain_length == {"a:pa": 1}
    assert request.blocks[0].memberships == (Membership("a:pa", 1, "h1"),)
    assert request.blocks[1].memberships == ()
    assert dict(registry.last_evidence_audit.problem_counts) == {
        "chain_prefix_broken": 1,
        "legal_hashed_candidate_without_membership": 1,
    }
    assert registry.last_evidence_audit.broken_chain_count == 1
    assert registry.last_evidence_audit.chain_states == (
        ("a:pa", 3, (1, 3), 1, "KNOWN"),
    )


def test_registry_keeps_terminal_content_with_unknown_reuse_weight() -> None:
    registry = A2NativeSnapshotRegistry()
    registry.observe(A2NativeChainSnapshot("a:pa", (1,), ("h1",), "p"))

    request = registry.build_request(
        [EvictionCandidate(1, 0, True, 0, "h1")],
        _context(),
        (),
        tau_seconds=30.0,
    )

    assert request.blocks[0].memberships == (Membership("a:pa", 1, "h1"),)
    assert request.chain_length == {"a:pa": 1}
    assert request.reuse_weight == {}
    assert dict(registry.last_evidence_audit.problem_counts) == {
        "reuse_weight_unknown_after_logical_completion": 1
    }
    assert dict(registry.last_evidence_audit.identity_state_counts) == {
        "CONTENT_VERIFIED_WEIGHT_UNKNOWN": 1
    }
    assert registry.last_evidence_audit.chain_states == (
        ("a:pa", 1, (1,), 1, "UNKNOWN"),
    )
    adapter = A2NativeBlockAdapter(lambda _candidates, _context: request)
    assert adapter.select_victims([_candidate(1, 0)], _context()) == [1]
    assert adapter.last_audit is not None
    assert adapter.last_audit.fallbacks == ("reuse_weight_missing",)


def test_registry_slot_reuse_rejects_delayed_old_eviction() -> None:
    registry = A2NativeSnapshotRegistry()
    registry.observe(A2NativeChainSnapshot("old:p", (1,), ("old",), "p"))
    registry.observe(A2NativeChainSnapshot("new:p", (1,), ("new",), "p"))

    registry.observe_eviction(1, content_hash="old", native_hash_process_id="p")

    identity = registry.content_identity(1)
    assert identity is not None
    assert identity.content_hash == "new"
    old = registry.chain_state("old:p")
    new = registry.chain_state("new:p")
    assert old is not None and old.reusable_prefix_blocks == 0
    assert new is not None and new.reusable_prefix_blocks == 1


def test_registry_fails_closed_when_one_shared_chain_proof_is_missing() -> None:
    registry = A2NativeSnapshotRegistry()
    registry.observe(A2NativeChainSnapshot("a:pa", (1, 2), ("h1", "h2"), "p"))
    candidates = [
        EvictionCandidate(1, 0, True, 0, "h1"),
        EvictionCandidate(2, 0, True, 1, "h2"),
        EvictionCandidate(3, 0, True, 2, "h3"),
    ]

    request = registry.build_request(
        candidates,
        _context(2),
        (_entry("a", "pa", (1, 2)), _entry("b", "pb", (1, 3))),
        tau_seconds=30.0,
    )

    assert request.blocks[0].memberships == ()
    adapter = A2NativeBlockAdapter(lambda _candidates, _context: request)
    assert adapter.select_victims(candidates, _context(2)) == [1, 2]
    assert adapter.last_audit is not None
    assert adapter.last_audit.fallbacks == ("content_unverified",)


def test_registry_fails_closed_on_candidate_hash_mismatch() -> None:
    registry = A2NativeSnapshotRegistry()
    registry.observe(A2NativeChainSnapshot("a:pa", (1,), ("expected",), "p"))
    candidates = [EvictionCandidate(1, 0, True, 0, "different")]

    request = registry.build_request(
        candidates,
        _context(),
        (_entry("a", "pa", (1,)),),
        tau_seconds=30.0,
    )

    assert request.blocks[0].memberships == ()
    assert dict(registry.last_evidence_audit.problem_counts)[
        "candidate_content_hash_mismatch"
    ] == 1
    adapter = A2NativeBlockAdapter(lambda _candidates, _context: request)
    assert adapter.select_victims(candidates, _context()) == [1]
    assert adapter.last_audit is not None
    assert adapter.last_audit.fallbacks == ("content_unverified",)
