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
            "backend_options": {"replay_token_ids_by_request": {"r": [1 if arm != "A2" else 2]}},
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
