import json
from pathlib import Path

import pytest

from kvopt.workload.continuum_w1a_acquisition import (
    AcquisitionRecorder,
    ObservedEnvironment,
    ObservedModel,
)
from kvopt.workload.continuum_w1a_conversion import (
    build_sidecar_evidence,
    main,
    resolve_instance_id,
)
from kvopt.workload.continuum_w1a_runner import (
    load_acquisition_config,
    validate_instance_id,
)

ROOT = Path(__file__).parents[1]


class _Clock:
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


class _Model:
    n_calls = 0

    def query(self, messages):
        self.n_calls += 1
        return {"content": "response"}


class _Environment:
    def execute(self, action):
        return {"output": f"ran {action}", "returncode": 0}


def _recorder(*, tokenize=True) -> AcquisitionRecorder:
    tokenizer = (
        (lambda messages: ("rendered:" + str(len(messages)), list(range(len(messages) + 1))))
        if tokenize
        else None
    )
    return AcquisitionRecorder(
        program_id="astropy__astropy-12907",
        provenance={"model": "test-model", "tokenizer_revision": "test-revision"},
        monotonic_clock=_Clock([1.0, 2.0, 3.0, 4.0]),
        wall_clock=_Clock([100.0]),
        tokenize_messages=tokenizer,
    )


def test_wrappers_capture_model_and_tool_boundaries_without_changing_results() -> None:
    recorder = _recorder()
    model = ObservedModel(_Model(), recorder)
    environment = ObservedEnvironment(_Environment(), recorder)
    messages = [{"role": "user", "content": "fix it"}]

    assert model.query(messages) == {"content": "response"}
    assert environment.execute("rg bug") == {"output": "ran rg bug", "returncode": 0}
    assert model.n_calls == 1
    assert recorder.model_calls[0]["request_id"] == "astropy__astropy-12907:turn:1"
    assert recorder.model_calls[0]["submitted_token_ids"] == [0, 1]
    assert recorder.tool_calls[0]["request_id"] == "astropy__astropy-12907:turn:1"


def test_sidecar_binds_trajectory_and_marks_observation_boundaries(tmp_path: Path) -> None:
    trajectory = tmp_path / "task.traj.json"
    trajectory.write_text("{}\n", encoding="utf-8")
    recorder = _recorder(tokenize=False)

    payload = recorder.to_dict(trajectory_path=trajectory)

    assert payload["trajectory_sha256"]
    assert payload["observation_boundaries"] == {
        "model_times": "WRAPPER_BOUNDARY_MONOTONIC",
        "tool_times": "WRAPPER_BOUNDARY_MONOTONIC",
        "token_ids": "NOT_OBSERVED",
        "native_apc_or_kv_residency": "NOT_OBSERVED",
    }


def test_sidecar_conversion_recovers_timing_and_token_growth(tmp_path: Path) -> None:
    trajectory = tmp_path / "task.traj.json"
    trajectory.write_text("{}\n", encoding="utf-8")
    recorder = _recorder()
    recorder.observe_model_call([{"role": "user", "content": "fix"}], dict)
    recorder.observe_tool_call("rg bug", lambda: {"output": "ok"})
    sidecar = recorder.to_dict(trajectory_path=trajectory)

    evidence = build_sidecar_evidence(
        sidecar,
        trajectory_path=trajectory,
        instance_id="astropy__astropy-12907",
    )

    assert evidence["model_call_count"] == 1
    assert evidence["tool_call_count"] == 1
    assert evidence["wrapper_timing_complete"] is True
    assert evidence["deterministic_tokenization_complete"] is True
    assert evidence["native_runtime_submitted_token_ids_observed"] is False
    assert evidence["requests"][0]["tool_evidence"]["status"] == "SUCCESS"


def test_sidecar_conversion_rejects_trajectory_hash_mismatch(tmp_path: Path) -> None:
    trajectory = tmp_path / "task.traj.json"
    trajectory.write_text("{}\n", encoding="utf-8")
    sidecar = _recorder(tokenize=False).to_dict(trajectory_path=trajectory)
    trajectory.write_text('{"changed":true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="trajectory SHA-256"):
        build_sidecar_evidence(
            sidecar,
            trajectory_path=trajectory,
            instance_id="astropy__astropy-12907",
        )


def test_recorder_preserves_failed_model_attempt() -> None:
    recorder = _recorder(tokenize=False)

    with pytest.raises(RuntimeError, match="offline"):
        recorder.observe_model_call([], lambda: (_ for _ in ()).throw(RuntimeError("offline")))

    assert recorder.model_calls[0]["status"] == "FAILED"
    assert recorder.model_calls[0]["error"] == "RuntimeError: offline"


def test_recorder_rejects_backwards_completion_time() -> None:
    recorder = AcquisitionRecorder(
        program_id="task",
        provenance={},
        monotonic_clock=_Clock([2.0, 1.0]),
        wall_clock=_Clock([100.0]),
    )

    with pytest.raises(ValueError, match="precedes"):
        recorder.observe_model_call([], lambda: {"content": "response"})


def test_external_instance_id_may_fill_but_not_override_source_identity() -> None:
    assert resolve_instance_id({"info": {}}, "external-id") == (
        "external-id",
        "EXTERNAL_FILL_FOR_MISSING_SOURCE_ID",
    )
    assert resolve_instance_id({"info": {"instance_id": "source-id"}}, None) == (
        "source-id",
        "SOURCE_TRAJECTORY",
    )
    with pytest.raises(ValueError, match="conflicts"):
        resolve_instance_id({"info": {"instance_id": "source-id"}}, "different-id")
    assert resolve_instance_id({"instance_id": "top-level-id", "info": {}}, None) == (
        "top-level-id",
        "SOURCE_TRAJECTORY",
    )
    with pytest.raises(ValueError, match="top-level and info"):
        resolve_instance_id(
            {"instance_id": "top-level-id", "info": {"instance_id": "info-id"}},
            None,
        )


def test_w1a_cli_returns_nonzero_when_validation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.json"
    source.write_text(
        json.dumps(
            {
                "trajectory_format": "mini-swe-agent-1",
                "info": {"instance_id": "task"},
                "messages": [
                    {"role": "user", "content": "fix"},
                    {"role": "assistant", "content": "done"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "kvopt.workload.continuum_w1a_conversion.validate_conversion",
        lambda *_args: {"verdict": "FAIL"},
    )
    monkeypatch.setattr(
        "sys.argv",
        ["converter", "--trajectory", str(source), "--output-root", str(tmp_path / "out")],
    )

    assert main() == 2


def test_acquisition_config_is_bound_to_frozen_w0_sample() -> None:
    config, sample = load_acquisition_config(
        ROOT / "configs/phase2/continuum-w1a-acquisition-v1.json",
        repository=ROOT,
    )

    assert config["dataset"]["revision"] == sample["dataset"]["revision"]
    assert config["author_runner"]["commit"] == sample["trajectory_source"][
        "repository_commit"
    ]
    assert config["acquisition"]["formal_native_campaign_authorized"] is False
    assert config["model"]["model_name"] == "Qwen/Qwen2.5-Coder-3B-Instruct"
    assert config["model"]["model_revision"] == "2ffd030b308f6bdd29ee43e7383f30ce8ac2e225"
    assert config["server_runtime"] == {
        "backend": "vllm-metal",
        "vllm_version": "0.27.1+cpu",
        "vllm_metal_version": "0.3.0",
        "host": "127.0.0.1",
        "port": 8100,
        "max_model_len": 16384,
        "gpu_memory_utilization": 0.75,
        "environment": {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "VLLM_ENABLE_V1_MULTIPROCESSING": "0",
        },
    }
    validate_instance_id("astropy__astropy-12907", sample)


def test_acquisition_rejects_task_outside_frozen_sample() -> None:
    _config, sample = load_acquisition_config(
        ROOT / "configs/phase2/continuum-w1a-acquisition-v1.json",
        repository=ROOT,
    )

    with pytest.raises(ValueError, match="not in the frozen"):
        validate_instance_id("django__django-99999", sample)
