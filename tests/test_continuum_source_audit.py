import copy
import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.continuum_source_audit import (
    convert_mini_swe_trajectory,
    validate_conversion,
)

ROOT = Path(__file__).parents[1]


def _trajectory(*, observed: bool = False) -> dict[str, object]:
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "repair the repository"},
        {"role": "user", "content": "fix issue X"},
        {"role": "assistant", "content": "```bash\nrg bug\n```"},
        {"role": "user", "content": "Observation: bug.py:4"},
        {"role": "assistant", "content": "```bash\nCOMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"},
    ]
    if observed:
        messages[2]["timestamp_seconds"] = 10.0
        messages[2]["input_token_ids"] = [1, 2, 3]
        messages[3]["timestamp_seconds"] = 10.25
        messages[4]["timestamp_seconds"] = 11.0
        messages[4]["input_token_ids"] = [1, 2, 3, 4]
    return {
        "trajectory_format": "mini-swe-agent-1",
        "info": {"instance_id": "repo__project-1"},
        "messages": messages,
    }


def test_conversion_preserves_logical_history_without_claiming_literal_prefix() -> None:
    source = _trajectory(observed=True)
    trace, report = convert_mini_swe_trajectory(source)

    assert len(trace.requests) == 2
    assert trace.requests[1].prefix_prompt == ""
    assert not trace.requests[1].prompt.startswith(trace.requests[0].prompt)
    assert trace.requests[0].tool_gap_seconds == 0.0
    assert "Observation: bug.py:4" in trace.requests[1].prompt
    assert report["conversion_verdict"] == "CONDITIONAL_PASS_STRUCTURAL_ONLY"
    assert report["fidelity"]["literal_prompt_prefix_verified"] is False
    assert validate_conversion(source, trace, report)["verdict"] == "CONDITIONAL_PASS"


def test_conversion_marks_public_schema_missing_timing_and_tokens() -> None:
    source = _trajectory()
    trace, report = convert_mini_swe_trajectory(source)

    assert trace.requests[0].planned_arrival_offset_seconds == 0.0
    assert report["conversion_verdict"] == "CONDITIONAL_PASS_STRUCTURAL_ONLY"
    assert validate_conversion(source, trace, report)["verdict"] == "CONDITIONAL_PASS"


def test_token_prefix_status_is_recomputed_from_observed_ids() -> None:
    source = _trajectory(observed=True)
    source["messages"][4]["input_token_ids"] = [9, 10]

    _trace, report = convert_mini_swe_trajectory(source)

    assert report["request_evidence"][1]["previous_submitted_tokens_are_prefix"] is False
    assert report["fidelity"]["submitted_token_prefix_verified"] is False


def test_validation_rejects_prompt_drift() -> None:
    source = _trajectory(observed=True)
    trace, report = convert_mini_swe_trajectory(source)
    changed = copy.deepcopy(source)
    changed["messages"][1]["content"] = "different task"

    assert validate_conversion(changed, trace, report)["verdict"] == "FAIL"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_trajectory_sha256", "0" * 64),
        ("instance_id", "tampered"),
        ("conversion_verdict", "PASS"),
    ],
)
def test_validation_rejects_tampered_report(field: str, value: object) -> None:
    source = _trajectory(observed=True)
    trace, report = convert_mini_swe_trajectory(source)
    changed = copy.deepcopy(report)
    changed[field] = value

    assert validate_conversion(source, trace, changed)["verdict"] == "FAIL"


def test_validation_rejects_tampered_request_hash() -> None:
    source = _trajectory(observed=True)
    trace, report = convert_mini_swe_trajectory(source)
    changed = copy.deepcopy(report)
    changed["request_evidence"][0]["materialized_prompt_sha256"] = "0" * 64

    assert validate_conversion(source, trace, changed)["verdict"] == "FAIL"


@pytest.mark.parametrize("bad_timestamp", [float("nan"), float("inf")])
def test_conversion_rejects_nonfinite_timestamps(bad_timestamp: float) -> None:
    source = _trajectory(observed=True)
    source["messages"][2]["timestamp_seconds"] = bad_timestamp

    with pytest.raises(ValueError, match="finite"):
        convert_mini_swe_trajectory(source)


def test_conversion_rejects_out_of_order_message_timestamps() -> None:
    source = _trajectory(observed=True)
    source["messages"][4]["timestamp_seconds"] = 9.0

    with pytest.raises(ValueError, match="non-decreasing"):
        convert_mini_swe_trajectory(source)


def test_conversion_rejects_unsupported_or_empty_trajectory() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        convert_mini_swe_trajectory({"trajectory_format": "other"}, instance_id="x")
    with pytest.raises(ValueError, match="no model requests"):
        convert_mini_swe_trajectory(
            {
                "trajectory_format": "mini-swe-agent-1",
                "messages": [{"role": "user", "content": "x"}],
            },
            instance_id="x",
        )


def test_w0_sample_and_seal_are_fixed_and_self_consistent() -> None:
    sample_path = ROOT / "configs/phase2/continuum-swebench-w0-sample-v1.json"
    seal_path = ROOT / "configs/phase2/continuum-swebench-w0-seal-v1.json"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    seal = json.loads(seal_path.read_text(encoding="utf-8"))

    assert sample["selection"] == {
        "rule": "first 10 rows in the pinned test split order",
        "sample_count": 10,
        "seed": None,
        "frozen_before_trajectory_acquisition": True,
    }
    assert len(sample["instance_ids"]) == len(set(sample["instance_ids"])) == 10
    for relative_path, expected in seal["bindings"].items():
        actual = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        assert actual == expected
    assert seal["formal_native_campaign_authorized"] is False
