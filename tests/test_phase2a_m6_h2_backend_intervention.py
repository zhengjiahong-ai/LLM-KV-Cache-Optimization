from types import SimpleNamespace

import pytest

from kvopt.continuum import PrefixIdentity, ProgramIdentity, ProgramStarted
from kvopt.runtime.vllm.h2_intervention import NativeBlockPoolCapture
from kvopt.workload.phase2 import PlannedRequest
from scripts.spikes.phase2_minimal_observability_metal import (
    MinimalMetalObservabilityBackend,
    _h2_native_prefix_interventions,
)


def test_h2_backend_interventions_are_keyed_by_exact_request_id() -> None:
    parsed = _h2_native_prefix_interventions(
        {
            "h2_native_prefix_interventions": {
                "probe-a:turn:1": {"position": "trailing", "count": 16}
            }
        }
    )

    assert parsed == {"probe-a:turn:1": ("trailing", 16)}


@pytest.mark.parametrize(
    "spec",
    [
        {"position": "middle", "count": 1},
        {"position": "leading", "count": -1},
        {"position": "leading", "count": 1, "extra": True},
    ],
)
def test_h2_backend_rejects_ambiguous_intervention_specs(spec) -> None:
    with pytest.raises((TypeError, ValueError)):
        _h2_native_prefix_interventions({"h2_native_prefix_interventions": {"probe:turn:1": spec}})


def test_h2_backend_applies_intervention_and_emits_auditable_event() -> None:
    pool = SimpleNamespace(
        blocks=[
            SimpleNamespace(block_hash=bytes([index]), ref_cnt=0, is_null=False)
            for index in range(4)
        ]
    )

    def evict(block) -> bool:
        block.block_hash = None
        return True

    pool._maybe_evict_cached_block = evict
    capture = NativeBlockPoolCapture(lambda _context: None)
    capture(SimpleNamespace(target="BlockPool.get_new_blocks", receiver=pool))
    emitted = []
    backend = MinimalMetalObservabilityBackend.__new__(MinimalMetalObservabilityBackend)
    backend._h2_interventions = {"probe:turn:1": ("leading", 2)}
    backend._applied_h2_interventions = set()
    backend._native_pool_capture = capture
    backend._sink = SimpleNamespace(emit=emitted.append)
    backend._clock = SimpleNamespace(now=lambda: 12.5)
    request = PlannedRequest(
        program_id="probe",
        request_id="probe:turn:1",
        turn_index=1,
        planned_arrival_offset_seconds=0.0,
        prompt="probe",
        prefix_prompt="probe",
        is_terminal=False,
        next_tool_type="search",
        tool_gap_seconds=0.1,
    )

    backend._apply_h2_intervention(
        request,
        PrefixIdentity("prefix:probe"),
        (0, 1, 2, 3),
        tuple(bytes([index]) for index in range(4)),
    )

    assert [block.block_hash for block in pool.blocks] == [None, None, b"\x02", b"\x03"]
    assert backend._applied_h2_interventions == {"probe:turn:1"}
    assert emitted[0].event_type == "H2_NATIVE_PREFIX_INTERVENTION"
    assert emitted[0].payload.to_dict()["selected_positions"] == [0, 1]


def test_h2_mechanism_only_emits_lifecycle_without_ttl_runtime() -> None:
    emitted = []
    backend = MinimalMetalObservabilityBackend.__new__(
        MinimalMetalObservabilityBackend
    )
    backend._h2_native_mechanism_only = True
    backend._sink = SimpleNamespace(emit=emitted.append)
    backend._runtime = SimpleNamespace(
        handle=lambda _event: pytest.fail("mechanism-only path called TTL runtime")
    )

    backend._handle_lifecycle(ProgramStarted(ProgramIdentity("probe"), 1.0))

    assert emitted[0].event_type == "PROGRAM_STARTED"
    assert emitted[0].program_id == ProgramIdentity("probe")
