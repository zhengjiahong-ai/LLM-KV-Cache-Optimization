import copy
import json
from pathlib import Path

import pytest

from kvopt.workload.phase2_h2_mechanism import materialize_formal_m2_m3
from kvopt.workload.phase2_h2_mechanism_runner import (
    _validate_direct_evidence,
    execute_formal_m2_m3,
)

AUTHORIZATION = (
    Path(__file__).parents[1] / "configs/phase2/h2-measurement-authorization.json"
)


def test_formal_m2_m3_materializes_frozen_cells_and_controls(tmp_path: Path) -> None:
    campaign_path = materialize_formal_m2_m3(
        AUTHORIZATION,
        tmp_path / "formal-m2-m3",
    )
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))

    assert campaign["m2_probe_count"] == 6
    assert campaign["m3_arm_count"] == 24
    assert campaign["m3_cell_count"] == 12
    assert campaign["probe_count"] == 30
    assert campaign["planned_run_count"] == 330
    assert not campaign["formal_verdict_authorized"]
    controls = {
        probe["control"]
        for probe in campaign["probes"]
        if probe["measurement"] == "M2" and probe["control"] is not None
    }
    assert controls == {"full-evict", "full-retain", "no-eviction-full-hit"}
    assert all(len(probe["runs"]) == 11 for probe in campaign["probes"])


def test_formal_m3_uses_equal_leading_and_trailing_arms(tmp_path: Path) -> None:
    campaign_path = materialize_formal_m2_m3(
        AUTHORIZATION,
        tmp_path / "formal-m2-m3",
    )
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    arms = [probe for probe in campaign["probes"] if probe["measurement"] == "M3"]

    assert {(probe["prefix_tokens"], probe["evicted_blocks"]) for probe in arms} == {
        (tokens, count)
        for tokens in (512, 2048, 8192, 24576)
        for count in (1, 4, 16)
    }
    assert all(
        {probe["position"] for probe in arms if probe["cell_id"] == cell_id}
        == {"leading", "trailing"}
        for cell_id in {probe["cell_id"] for probe in arms}
    )


def test_formal_m2_m3_rejects_changed_frozen_rule(tmp_path: Path) -> None:
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    changed = copy.deepcopy(authorization)
    changed["protocol"]["m3_rules"]["supporting_cells_required"] = 9
    changed_path = tmp_path / "changed-authorization.json"
    changed_path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="M3 rules differ"):
        materialize_formal_m2_m3(changed_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_formal_m2_m3_rejects_changed_authorized_base_config(
    tmp_path: Path,
) -> None:
    authorization = json.loads(AUTHORIZATION.read_text(encoding="utf-8"))
    authorization["m1_execution_configurations"][0]["config"]["seed"] = 99
    changed_path = tmp_path / "changed-authorization.json"
    changed_path.write_text(json.dumps(authorization), encoding="utf-8")

    with pytest.raises(ValueError, match="base configuration hash mismatch"):
        materialize_formal_m2_m3(changed_path, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_formal_m2_m3_runner_rejects_changed_config_before_execution(
    tmp_path: Path,
) -> None:
    campaign_path = materialize_formal_m2_m3(
        AUTHORIZATION,
        tmp_path / "formal-m2-m3",
    )
    config_path = campaign_path.parent / "m2-k0.config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["generation"]["max_new_tokens"] = 2
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="differs from authorization"):
        execute_formal_m2_m3(
            campaign_path,
            AUTHORIZATION,
            tmp_path / "runs",
        )
    assert not (tmp_path / "runs").exists()


def test_formal_m2_m3_runner_rejects_changed_trace_before_execution(
    tmp_path: Path,
) -> None:
    campaign_path = materialize_formal_m2_m3(
        AUTHORIZATION,
        tmp_path / "formal-m2-m3",
    )
    trace_path = campaign_path.parent / "m3-r512-j1-leading.trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace["requests"][1]["prompt"] = "changed"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    with pytest.raises(ValueError, match="differs from frozen trace"):
        execute_formal_m2_m3(
            campaign_path,
            AUTHORIZATION,
            tmp_path / "runs",
        )
    assert not (tmp_path / "runs").exists()


def test_formal_mechanism_run_requires_direct_intervention_and_return_evidence(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    run.mkdir()
    events = [
        {
            "event_type": "H2_NATIVE_PREFIX_INTERVENTION",
            "request_id": "m3-r512-j4-leading:turn:1",
            "payload": {
                "position": "leading",
                "count": 4,
                "ownership_changed": False,
                "queue_reordered": False,
            },
        },
        {
            "event_type": "VLLM_NATIVE_REQUEST_OBSERVATION",
            "request_id": "m3-r512-j4-leading:turn:2",
            "payload": {
                "native_prompt_tokens": 513,
                "native_cached_prefix_tokens": 0,
            },
        },
    ]
    (run / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    probe = {
        "probe_id": "m3-r512-j4-leading",
        "prefix_tokens": 512,
        "position": "leading",
        "evicted_blocks": 4,
    }

    _validate_direct_evidence(run, probe)

    events[1]["payload"].pop("native_cached_prefix_tokens")
    (run / "events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="token evidence is invalid"):
        _validate_direct_evidence(run, probe)
