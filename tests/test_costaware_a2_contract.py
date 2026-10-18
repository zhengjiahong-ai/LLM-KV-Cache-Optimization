"""Tests for the frozen A2 decision contract.

The contract is what M6 implements against, so the tests pin three things: that a
well-formed request builds a scorable geometry, that malformed requests are reported
rather than thrown, and that post-decision fields can never become inputs.
"""

from __future__ import annotations

import pytest

from kvopt.costaware.a2_contract import (
    ALREADY_AVAILABLE,
    DERIVED_IN_ENGINE,
    EVALUATION_ONLY,
    FIELD_CONTRACT,
    NEEDS_EXPOSURE,
    BlockDecisionInput,
    DecisionRequest,
    assert_no_evaluation_fields,
    evaluation_only_fields,
    fields_by_provenance,
    fields_needing_exposure,
    validate_request,
)
from kvopt.costaware.a2_geometry import Membership
from kvopt.costaware.a2_selector import SELECTOR_NATIVE_FALLBACK, select_victims


def _request(**overrides) -> DecisionRequest:
    base = {
        "required_blocks": 2,
        "timestamp": 100.0,
        "blocks": (
            BlockDecisionInput(
                block_id=1,
                native_rank=0,
                memberships=(Membership("a", 3, "h1"),),
            ),
            BlockDecisionInput(
                block_id=2,
                native_rank=1,
                memberships=(Membership("a", 2, "h2"),),
            ),
            BlockDecisionInput(block_id=3, native_rank=2, has_block_hash=False),
        ),
        "chain_length": {"a": 3},
        "reuse_weight": {"a": 0.4},
    }
    base.update(overrides)
    return DecisionRequest(**base)


# --- field contract -------------------------------------------------------


def test_contract_covers_every_provenance_class() -> None:
    provenances = {field.provenance for field in FIELD_CONTRACT}
    assert provenances == {
        ALREADY_AVAILABLE,
        DERIVED_IN_ENGINE,
        NEEDS_EXPOSURE,
        EVALUATION_ONLY,
    }


def test_only_two_fields_need_exposure() -> None:
    """Keep the ask to M6 minimal."""
    names = {field.name for field in fields_needing_exposure()}
    assert names == {"content_hash", "reuse_weight"}


def test_evaluation_only_fields_are_named() -> None:
    names = {field.name for field in evaluation_only_fields()}
    assert names == {"observed_recomputed_tokens", "returned_after_decision"}


def test_depth_is_derived_not_exposed_and_not_rank() -> None:
    depth = next(f for f in FIELD_CONTRACT if f.name == "prefix_depth")
    assert depth.provenance == DERIVED_IN_ENGINE
    assert "must NOT be inferred from native_lru_rank" in depth.description


def test_block_id_carries_an_invalidation_rule() -> None:
    block_id = next(f for f in FIELD_CONTRACT if f.name == "block_id")
    assert "not content" in block_id.invalidated_by
    assert block_id.validity


def test_chain_id_requires_all_memberships() -> None:
    chain = next(f for f in FIELD_CONTRACT if f.name == "chain_id")
    assert "several chains" in chain.description
    assert "understates" in chain.description


def test_reuse_weight_validity_is_stated() -> None:
    weight = next(f for f in FIELD_CONTRACT if f.name == "reuse_weight")
    assert weight.provenance == NEEDS_EXPOSURE
    assert "unscorable" in weight.description


def test_assert_no_evaluation_fields_rejects_leaks() -> None:
    with pytest.raises(ValueError, match="post-decision"):
        assert_no_evaluation_fields(["block_id", "returned_after_decision"])


def test_assert_no_evaluation_fields_accepts_clean_input() -> None:
    assert_no_evaluation_fields(["block_id", "native_lru_rank", "content_hash"])


def test_fields_by_provenance_partitions_the_contract() -> None:
    total = sum(
        len(fields_by_provenance(p))
        for p in (ALREADY_AVAILABLE, DERIVED_IN_ENGINE, NEEDS_EXPOSURE, EVALUATION_ONLY)
    )
    assert total == len(FIELD_CONTRACT)


# --- request validation ---------------------------------------------------


def test_valid_request_reports_no_problem() -> None:
    assert validate_request(_request()) == ()


def test_hashless_block_needs_no_membership() -> None:
    request = _request()
    hashless = next(b for b in request.blocks if not b.has_block_hash)
    assert hashless.memberships == ()
    assert validate_request(request) == ()


def test_hashless_block_claiming_membership_is_rejected() -> None:
    request = _request(
        blocks=(
            BlockDecisionInput(
                block_id=1,
                native_rank=0,
                has_block_hash=False,
                memberships=(Membership("a", 1, "h1"),),
            ),
        )
    )
    assert any("hashless but claims" in p for p in validate_request(request))


def test_duplicate_block_ids_are_reported() -> None:
    request = _request(
        blocks=(
            BlockDecisionInput(1, 0, memberships=(Membership("a", 2, "h"),)),
            BlockDecisionInput(1, 1, memberships=(Membership("a", 1, "h2"),)),
        )
    )
    assert any("duplicate block id" in p for p in validate_request(request))


def test_depth_outside_the_chain_is_reported() -> None:
    request = _request(
        blocks=(
            BlockDecisionInput(1, 0, memberships=(Membership("a", 9, "h"),)),
        ),
        chain_length={"a": 3},
    )
    assert any("exceeds chain" in p for p in validate_request(request))


def test_unknown_chain_length_is_reported() -> None:
    request = _request(
        blocks=(
            BlockDecisionInput(1, 0, memberships=(Membership("z", 1, "h"),)),
        ),
        chain_length={"a": 3},
    )
    assert any("unknown length" in p for p in validate_request(request))


def test_out_of_range_reuse_weight_is_reported() -> None:
    request = _request(reuse_weight={"a": 1.5})
    assert any("outside (0, 1]" in p for p in validate_request(request))


def test_negative_required_blocks_is_reported() -> None:
    assert any(
        "non-negative" in p for p in validate_request(_request(required_blocks=-1))
    )


def test_empty_legal_set_is_reported() -> None:
    assert any("no legal blocks" in p for p in validate_request(_request(blocks=())))


# --- request to geometry --------------------------------------------------


def test_request_builds_a_scorable_geometry() -> None:
    geometry = _request().to_geometry()
    assert geometry.scorable
    assert geometry.gaps == {}
    assert geometry.unknown_weight_chains == ()
    assert geometry.chain_length == {"a": 3}


def test_missing_reuse_weight_becomes_unknown_and_forces_fallback() -> None:
    request = _request(reuse_weight={})
    geometry = request.to_geometry()

    assert not geometry.scorable
    assert geometry.unknown_weight_chains == ("a",)

    selection = select_victims(geometry, 2)
    assert selection.selector == SELECTOR_NATIVE_FALLBACK


def test_hashed_block_without_membership_becomes_a_gap() -> None:
    request = _request(
        blocks=(
            BlockDecisionInput(block_id=1, native_rank=0),
            BlockDecisionInput(block_id=2, native_rank=1, has_block_hash=False),
        )
    )
    geometry = request.to_geometry()
    assert geometry.gaps == {1: "content_unverified"}
    assert not geometry.scorable


def test_hashless_block_is_not_a_gap() -> None:
    request = _request(
        blocks=(BlockDecisionInput(block_id=1, native_rank=0, has_block_hash=False),)
    )
    geometry = request.to_geometry()
    assert geometry.gaps == {}
    assert geometry.scorable


def test_selector_on_a_well_formed_request_reaches_the_cost_model() -> None:
    geometry = _request().to_geometry()
    selection = select_victims(geometry, 2)
    assert selection.cost_known
    assert not selection.is_fallback
    assert set(selection.blocks) <= {1, 2, 3}
