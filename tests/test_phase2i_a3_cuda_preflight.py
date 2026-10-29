from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload import phase2i_a3_cuda_preflight as module


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _source(tmp_path: Path) -> tuple[Path, Path, Path]:
    requests = [
        {
            "program_id": "program",
            "request_id": f"request-{index}",
            "turn_index": index,
            "planned_arrival_offset_seconds": 0.0,
            "prompt": "prompt",
            "prefix_prompt": "",
            "is_terminal": False,
            "next_tool_type": "gap",
            "tool_gap_seconds": 0.0,
            "kind": "turn",
        }
        for index in range(180)
    ]
    trace = tmp_path / "source.trace.json"
    _write(
        trace,
        {
            "schema_version": "phase2.trace.v1",
            "trace_id": "phase2h-hr02-short-gap-long-context",
            "allow_incomplete_programs": True,
            "requests": requests,
            "pressure_stages": [],
        },
    )
    replay = {row["request_id"]: [index, index + 1] for index, row in enumerate(requests)}
    submissions = {
        key: hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for key, value in replay.items()
    }
    pressure_stages = {
        boundary: {
            "stage_id": boundary.removeprefix("pressure:"),
            "prompt": boundary,
            "max_requests": 1,
            "stop_on_forced_release": False,
        }
        for boundary in module.PRESSURE_BOUNDARIES
    }
    config = tmp_path / "source.config.json"
    _write(
        config,
        {
            "schema_version": "phase2.config.v1",
            "campaign_kind": "phase2h_history_rich_native_smoke",
            "runtime_mode": "vllm-cuda-observability",
            "backend_factory": "factory:build",
            "backend_revision": "phase2h-history-rich-cuda-v1",
            "model": {
                "name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
                "revision": module.MODEL_REVISION,
            },
            "tokenizer": {
                "name": "Qwen/Qwen2.5-Coder-1.5B-Instruct",
                "revision": module.MODEL_REVISION,
            },
            "generation": {"max_new_tokens": 1, "temperature": 0.0},
            "cache": {"block_override": 2048, "block_size": 16},
            "batching": {"max_concurrent_requests": 2},
            "pressure": {
                "initial_shortage_blocks": 128,
                "required_blocks": 379,
                "safety_ceiling": 1,
            },
            "seed": 20261121,
            "observe": True,
            "policy": "continuum-a1-entry-native-lru",
            "trace": trace.name,
            "controlled_sparse_replay": {
                "logical_sequence_sha256": "timeline-sha",
            },
            "backend_options": {
                "phase2g_release_policy": "A1",
                "phase2g_block_policy": "A0",
                "replay_token_ids_by_request": replay,
                "expected_native_submission_sha256_by_request": submissions,
                "controlled_pressure_stages_by_boundary": pressure_stages,
                "pressure_token_ids_by_stage": {
                    stage["stage_id"]: [index, index + 1]
                    for index, stage in enumerate(pressure_stages.values())
                },
                "prefill_profile_path": "old-profile.json",
            },
        },
    )
    profile = tmp_path / "profile.json"
    _write(profile, {"schema_version": "profile"})
    return config, trace, profile


def test_materialize_changes_only_authorized_runtime_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "abc123",
    )
    output = tmp_path / "prepared"

    manifest = module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        output_dir=output,
        repository=tmp_path,
    )

    derived = json.loads(
        (output / f"{module.RUN_ID}.config.json").read_text(encoding="utf-8")
    )
    assert manifest["git_sha"] == "abc123"
    assert derived["campaign_kind"] == "phase2i_a3_native_integration"
    assert derived["backend_options"]["phase2g_release_policy"] == "A3"
    assert derived["backend_options"]["phase2g_block_policy"] == "A0"
    assert derived["cache"] == {"block_override": 2048, "block_size": 16}
    assert derived["pressure"] == {
        "initial_shortage_blocks": 128,
        "required_blocks": 379,
        "safety_ceiling": 1,
    }
    assert (output / "hr02-short-gap-long-context.trace.json").read_bytes() == trace.read_bytes()


def test_materialize_rejects_pressure_or_explicit_token_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    value = json.loads(config.read_text(encoding="utf-8"))
    value["pressure"]["required_blocks"] = 378
    _write(config, value)
    monkeypatch.setattr(module, "_git", lambda *_args: "abc123")

    with pytest.raises(ValueError, match="pressure geometry drifted"):
        module.materialize_preflight(
            source_config_path=config,
            source_trace_path=trace,
            profile_path=profile,
            output_dir=tmp_path / "prepared",
            repository=tmp_path,
        )


def test_verify_freeze_rejects_git_or_file_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, trace, profile = _source(tmp_path)
    monkeypatch.setattr(
        module,
        "_git",
        lambda _repository, *arguments: "" if arguments[0] == "status" else "abc123",
    )
    output = tmp_path / "prepared"
    module.materialize_preflight(
        source_config_path=config,
        source_trace_path=trace,
        profile_path=profile,
        output_dir=output,
        repository=tmp_path,
    )
    (output / "hr02-short-gap-long-context.trace.json").write_text(
        "{}\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="trace_sha256"):
        module._verify_freeze(output, tmp_path)
