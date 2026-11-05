from __future__ import annotations

import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from kvopt.workload.phase2 import load_phase2_trace
from kvopt.workload.phase3_materialize import (
    ARMS,
    CAMPAIGN_KIND,
    arm_binding,
    materialize_six_arm_cell,
    pressure_request_contract,
    validate_pressure_identity,
)
from kvopt.workload.phase3_native_preflight import materialize_native_preflight


def _base() -> dict[str, object]:
    return {
        "schema_version": "phase2.config.v1",
        "execution_authorized": False,
        "trace": "frozen.trace.json",
        "pressure": {"required_blocks": 32},
        "controlled_sparse_replay": {
            "boundaries": [{"boundary_id": "pressure:1", "logical_timestamp": 1.0}]
        },
        "backend_options": {
            "replay_token_ids_by_request": {"r": [1, 2, 3]},
            "pressure_token_ids_by_stage": {"p": [4, 5]},
            "controlled_pressure_stages_by_boundary": {
                "pressure:1": {
                    "stage_id": "p",
                    "prompt": "fixed pressure",
                    "max_requests": 3,
                    "stop_on_forced_release": True,
                }
            },
        },
    }


def _trace(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "phase2.trace.v1",
                "trace_id": "phase3-test-trace",
                "requests": [
                    {
                        "program_id": "program-a",
                        "request_id": "r",
                        "turn_index": 1,
                        "planned_arrival_offset_seconds": 0.0,
                        "prompt": "frozen",
                        "prefix_prompt": "",
                        "is_terminal": True,
                        "next_tool_type": None,
                        "tool_gap_seconds": None,
                    }
                ],
                "pressure_stages": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_materializes_six_unauthorized_configs_with_one_shared_input(tmp_path: Path) -> None:
    manifest = materialize_six_arm_cell(
        base_config=_base(),
        trace_path=_trace(tmp_path / "source.trace.json"),
        cell_id="g01-low",
        output_dir=tmp_path / "cell",
    )

    assert tuple(manifest["arms"]) == ARMS
    assert manifest["execution_authorized"] is False
    assert len(manifest["runs"]) == 6
    assert {row["shared_input_sha256"] for row in manifest["runs"]} == {
        manifest["shared_input_sha256"]
    }
    configs = {
        row["arm"]: json.loads(
            (tmp_path / "cell" / row["config"]).read_text(encoding="utf-8")
        )
        for row in manifest["runs"]
    }
    assert all(config["campaign_kind"] == CAMPAIGN_KIND for config in configs.values())
    assert all(config["pressure"] == _base()["pressure"] for config in configs.values())
    assert all(
        config["controlled_sparse_replay"] == _base()["controlled_sparse_replay"]
        for config in configs.values()
    )
    assert configs["N0"]["backend_options"]["phase2g_release_policy"] == "N0"
    assert configs["E0"]["backend_options"]["phase2g_release_policy"] == "E0"
    assert configs["A2"]["backend_options"]["phase2g_block_policy"] == "A2"
    assert all(
        config["backend_options"]["controlled_pressure_stages_by_boundary"]
        ["pressure:1"]["stop_on_forced_release"]
        is False
        for config in configs.values()
    )
    assert manifest["pressure_request_contract"][0]["request_ids"] == [
        "pressure:p:1",
        "pressure:p:2",
        "pressure:p:3",
    ]
    assert pressure_request_contract(configs["N0"]) == pressure_request_contract(
        configs["A0"]
    )
    assert pressure_request_contract(configs["N0"])[0]["boundary_id"] == (
        pressure_request_contract(configs["A0"])[0]["boundary_id"]
    )


def test_materializer_refuses_execution_authority(tmp_path: Path) -> None:
    base = _base()
    base["execution_authorized"] = True
    with pytest.raises(ValueError, match="cannot authorize execution"):
        materialize_six_arm_cell(
            base_config=base,
            trace_path=_trace(tmp_path / "source.trace.json"),
            cell_id="g01-low",
            output_dir=tmp_path / "cell",
        )


def test_arm_binding_rejects_unknown_arm() -> None:
    with pytest.raises(ValueError, match="unsupported Phase 3 arm"):
        arm_binding("AX")


def test_generated_configs_resolve_one_real_frozen_trace(tmp_path: Path) -> None:
    source = _trace(tmp_path / "source" / "trace.json")
    manifest = materialize_six_arm_cell(
        base_config=_base(),
        trace_path=source,
        cell_id="g01-low",
        output_dir=tmp_path / "cell",
    )

    trace_shas = set()
    for row in manifest["runs"]:
        config_path = tmp_path / "cell" / row["config"]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        resolved = config_path.parent / config["trace"]
        trace_shas.add(hashlib.sha256(resolved.read_bytes()).hexdigest())
        assert resolved.is_file()
        assert load_phase2_trace(resolved).trace_id == "phase3-test-trace"
    assert len(trace_shas) == 1
    assert trace_shas == {manifest["trace_sha256"]}


def test_pressure_isolation_rejects_policy_dependent_attempt_count(tmp_path: Path) -> None:
    manifest = materialize_six_arm_cell(
        base_config=_base(),
        trace_path=_trace(tmp_path / "source.trace.json"),
        cell_id="g01-low",
        output_dir=tmp_path / "cell",
    )
    configs = {
        row["arm"]: json.loads(
            (tmp_path / "cell" / row["config"]).read_text(encoding="utf-8")
        )
        for row in manifest["runs"]
    }
    n0_stage = configs["N0"]["backend_options"][
        "controlled_pressure_stages_by_boundary"
    ]["pressure:1"]
    n0_stage["max_requests"] = 4

    with pytest.raises(ValueError, match="pressure request identity differs"):
        validate_pressure_identity(configs)


def test_materializes_one_group_a0_native_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions = []
    timeline = []
    enqueue_order = []
    for session_index, program_id in enumerate(("program-a", "program-b")):
        calls = []
        selected = []
        for turn in range(1, 13):
            request_id = f"{program_id}:turn:{turn}"
            tokens = [session_index + 1] * (16 * turn)
            calls.append(
                {
                    "request_id": request_id,
                    "turn_index": turn,
                    "status": "SUCCESS",
                    "rendered_prompt": f"prompt-{request_id}",
                    "submitted_token_ids": tokens,
                    "model_submit_monotonic_seconds": float(turn * 2),
                    "model_completion_monotonic_seconds": float(turn * 2 + 1),
                }
            )
            selected.append(
                {
                    "request_id": request_id,
                    "token_count": len(tokens),
                    "token_ids_sha256": hashlib.sha256(
                        json.dumps(tokens, sort_keys=True, separators=(",", ":")).encode()
                    ).hexdigest(),
                }
            )
            enqueue_order.append(request_id)
            timeline.extend(
                (
                    {
                        "boundary_id": f"arrival:{request_id}",
                        "logical_timestamp": float(turn * 2 + session_index / 4),
                        "source": "test-submit",
                        "kind": "ARRIVAL",
                        "request_id": request_id,
                    },
                    {
                        "boundary_id": f"completion:{request_id}",
                        "logical_timestamp": float(turn * 2 + 1 + session_index / 4),
                        "source": "test-complete",
                        "kind": "COMPLETION",
                        "request_id": request_id,
                    },
                )
            )
        sidecar = tmp_path / f"{program_id}.json"
        sidecar.write_text(json.dumps({"model_calls": calls}), encoding="utf-8")
        sessions.append(
            {
                "instance_id": program_id,
                "sidecar_path": str(sidecar),
                "sidecar_sha256": hashlib.sha256(sidecar.read_bytes()).hexdigest(),
                "selected_requests": selected,
            }
        )
    timeline.sort(key=lambda row: (row["logical_timestamp"], row["kind"]))
    frozen_order = [
        str(row["request_id"]) for row in timeline if row["kind"] == "ARRIVAL"
    ]
    seal_path = tmp_path / "seal.json"
    seal_path.write_text(
        json.dumps(
            {
                "schema_version": "phase3.cohort_seal.v1",
                "groups": [
                    {
                        "group_id": "g14",
                        "sessions": sessions,
                        "frozen_request_order": frozen_order,
                        "native_enqueue_order": frozen_order,
                        "replay_timeline": timeline,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "kvopt.workload.phase3_native_preflight.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, "frozen-git-sha\n", ""),
    )

    freeze = materialize_native_preflight(
        repository=tmp_path,
        seal_path=seal_path,
        profile_path=profile,
        group_id="g14",
        output_dir=tmp_path / "output",
    )

    config = json.loads(
        (tmp_path / "output" / str(freeze["config"])).read_text(encoding="utf-8")
    )
    assert freeze["request_count"] == 24
    assert config["campaign_kind"] == "phase3_final_evaluation"
    assert config["cache"]["block_override"] == 2048
    assert config["backend_options"]["phase2g_release_policy"] == "A0"
    assert config["backend_options"]["controlled_pressure_stages_by_boundary"] == {}
    assert len(config["backend_options"]["replay_token_ids_by_request"]) == 24
