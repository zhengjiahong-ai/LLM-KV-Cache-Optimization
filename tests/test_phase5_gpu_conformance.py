from __future__ import annotations

from dataclasses import replace

import pytest

from kvopt.workload.phase5_gpu_conformance import (
    Readiness,
    build_phase5e_review_candidate,
)


def test_phase5e_candidate_is_non_executable_and_hashable() -> None:
    plan = build_phase5e_review_candidate("a" * 40)

    assert len(plan.programs) == 4
    assert plan.resource_budget.maximum_native_inflight == 4
    assert plan.execution_authorized is False
    assert plan.abort_readiness is Readiness.NOT_READY
    assert len(plan.sha256) == 64


def test_phase5e_requires_exactly_four_programs() -> None:
    plan = build_phase5e_review_candidate("a" * 40)

    with pytest.raises(ValueError, match="exactly four"):
        replace(plan, programs=plan.programs[:3])


def test_phase5e_requires_frozen_arrival_tie() -> None:
    plan = build_phase5e_review_candidate("a" * 40)
    programs = tuple(
        replace(
            program,
            arrival_offsets_seconds=(float(index), float(index + 10)),
        )
        for index, program in enumerate(plan.programs, start=1)
    )

    with pytest.raises(ValueError, match="Frozen Arrival tie"):
        replace(plan, programs=programs)


def test_phase5e_rejects_incomplete_enqueue_contract() -> None:
    plan = build_phase5e_review_candidate("a" * 40)

    with pytest.raises(ValueError, match="cover every request"):
        replace(plan, frozen_native_enqueue_order=plan.frozen_native_enqueue_order[:-1])


def test_phase5e_abort_readiness_requires_independent_confirmation() -> None:
    plan = build_phase5e_review_candidate("a" * 40)

    with pytest.raises(ValueError, match="independent confirmation"):
        replace(plan, abort_readiness=Readiness.READY_FOR_AUTHORIZATION_REVIEW)


def test_phase5e_cannot_self_authorize_execution() -> None:
    plan = build_phase5e_review_candidate("a" * 40)

    with pytest.raises(ValueError, match="must not authorize"):
        replace(plan, execution_authorized=True)
