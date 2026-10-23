import json
from pathlib import Path

from kvopt.workload.continuum_w1b_campaign import validate_campaign


def test_validate_campaign_rejects_cross_arm_token_mismatch(tmp_path: Path) -> None:
    trace = tmp_path / "g.trace.json"
    trace.write_text("{}\n", encoding="utf-8")
    import hashlib

    trace_sha = hashlib.sha256(trace.read_bytes()).hexdigest()
    runs = []
    for arm in ("A0", "A1", "A2"):
        config = {
            "trace": trace.name,
            "cache": {"block_override": 1},
            "pressure": {"required_blocks": 1},
            "seed": 1,
            "model": {"name": "m"},
            "tokenizer": {"name": "t"},
            "backend_options": {
                "replay_token_ids_by_request": {"r": [1 if arm != "A2" else 2]},
                "w1b_right_censored_end_request_ids": [],
            },
            "continuum_w1b_stage": {"arm": arm},
        }
        path = tmp_path / f"{arm}.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        runs.append(
            {
                "run_id": arm,
                "group_id": "g",
                "arm": arm,
                "repeat": 1,
                "config": path.name,
                "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "trace_sha256": trace_sha,
            }
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"planned_run_count": 12, "runs": runs * 4}), encoding="utf-8")
    report = validate_campaign(manifest_path=manifest)
    assert report["status"] == "FAIL"
    assert any("token identity mismatch" in item for item in report["problems"])


def test_prefix_accounting_uses_only_complete_cache_blocks() -> None:
    token_count = 2019
    assert token_count // 16 * 16 == 2016


def test_exact_token_mode_does_not_require_logical_segments() -> None:
    options = {"continuum_w1b_replay_mode": True}
    assert "phase2c_native_pilot_mode" not in options
    assert "prefix_segments_by_request" not in options


def test_validate_campaign_rejects_policy_independent_runtime_tampering(
    tmp_path: Path,
) -> None:
    import hashlib

    trace = tmp_path / "g.trace.json"
    trace.write_text("{}\n", encoding="utf-8")
    trace_sha = hashlib.sha256(trace.read_bytes()).hexdigest()
    runs = []
    for group in range(4):
        for arm in ("A0", "A1", "A2"):
            config = {
                "trace": trace.name,
                "cache": {"block_override": 1},
                "pressure": {"required_blocks": 1},
                "seed": 1,
                "model": {"name": "m"},
                "tokenizer": {"name": "t"},
                "generation": {"max_new_tokens": 2 if group == 0 and arm == "A2" else 1},
                "batching": {"max_concurrent_requests": 2},
                "policy": arm,
                "backend_options": {
                    "replay_token_ids_by_request": {"r": [1]},
                    "w1b_right_censored_end_request_ids": [],
                    "phase2g_release_policy": arm,
                    "phase2g_block_policy": "A0",
                },
                "continuum_w1b_stage": {"arm": arm},
            }
            path = tmp_path / f"g{group}-{arm}.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            runs.append(
                {
                    "run_id": f"g{group}-{arm}",
                    "group_id": f"g{group}",
                    "arm": arm,
                    "repeat": 1,
                    "config": path.name,
                    "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "trace_sha256": trace_sha,
                }
            )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"planned_run_count": 12, "runs": runs}), encoding="utf-8")

    report = validate_campaign(manifest_path=manifest)

    assert report["status"] == "FAIL"
    assert any("policy-independent config mismatch" in item for item in report["problems"])
