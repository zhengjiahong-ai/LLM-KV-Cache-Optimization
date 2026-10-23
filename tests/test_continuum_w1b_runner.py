import json
from pathlib import Path

import pytest

from kvopt.workload.continuum_w1b_runner import run_w1b


def test_w1b_runner_rejects_wrong_stage_before_creating_output(tmp_path: Path) -> None:
    config = {
        "schema_version": "phase2.config.v1",
        "campaign_kind": "continuum_w1b_native_smoke",
        "runtime_mode": "vllm-metal-observability",
        "model": {"name": "model", "revision": "revision"},
        "tokenizer": {"name": "model", "revision": "revision"},
        "generation": {"max_new_tokens": 1, "temperature": 0.0},
        "cache": {"block_size": 16, "block_override": 64},
        "batching": {"max_concurrent_requests": 1},
        "pressure": {"required_blocks": 1, "initial_shortage_blocks": 1, "safety_ceiling": 1},
        "policy": "continuum-a0-entry-native-lru",
        "seed": 1,
        "observe": True,
        "trace": "trace.json",
        "backend_factory": "unused:factory",
        "backend_revision": "test",
        "backend_options": {"continuum_w1b_replay_mode": True},
        "continuum_w1b_stage": {"stage": "WRONG"},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="not a Phase 2D"):
        run_w1b(config_path, output_root=tmp_path / "runs", run_id="run")
    assert not (tmp_path / "runs" / "run").exists()
