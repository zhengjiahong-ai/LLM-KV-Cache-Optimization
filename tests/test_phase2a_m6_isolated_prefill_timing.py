from types import SimpleNamespace

import pytest

from kvopt.runtime.vllm.prefill_timing import IsolatedPrefillTimingHook


class _Runner:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def _submit_paged_forward_outputs(self, *outputs: object) -> None:
        self.actions.append(f"submit:{len(outputs)}")

    def _start_paged_forward(
        self,
        batch: object,
        prefill_reqs: list[object],
        decode_reqs: list[object],
        scheduler_output: object,
    ) -> None:
        self.actions.append("build_forward")
        self._submit_paged_forward_outputs("logits")
        self.actions.append("return_before_sampling")


def test_isolated_prefill_hook_syncs_forward_before_sampling_boundary() -> None:
    clock_values = iter((4.0, 4.25))
    recorded: list[tuple[str, float]] = []
    runner = _Runner()

    with IsolatedPrefillTimingHook(
        _Runner,
        lambda *_outputs: runner.actions.append("synchronize"),
        lambda request_id, elapsed: recorded.append((request_id, elapsed)),
        clock=lambda: next(clock_values),
    ):
        runner._start_paged_forward(
            object(),
            [SimpleNamespace(req_id="native-1")],
            [],
            object(),
        )
        runner.actions.append("sampling")

    assert runner.actions == [
        "build_forward",
        "submit:1",
        "synchronize",
        "return_before_sampling",
        "sampling",
    ]
    assert recorded == [("native-1", pytest.approx(0.25))]


def test_isolated_prefill_hook_rejects_ambiguous_batch() -> None:
    runner = _Runner()
    with (
        IsolatedPrefillTimingHook(_Runner, lambda *_: None, lambda *_: None),
        pytest.raises(RuntimeError, match="one prefill and no decode"),
    ):
        runner._start_paged_forward(
            object(),
            [SimpleNamespace(req_id="one"), SimpleNamespace(req_id="two")],
            [],
            object(),
        )


def test_isolated_prefill_hook_restores_runner_methods() -> None:
    original_start = _Runner._start_paged_forward
    original_submit = _Runner._submit_paged_forward_outputs

    with IsolatedPrefillTimingHook(_Runner, lambda *_: None, lambda *_: None):
        assert _Runner._start_paged_forward is not original_start
        assert _Runner._submit_paged_forward_outputs is not original_submit

    assert _Runner._start_paged_forward is original_start
    assert _Runner._submit_paged_forward_outputs is original_submit
