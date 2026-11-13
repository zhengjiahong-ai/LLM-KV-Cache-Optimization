from __future__ import annotations

from kvopt.profiling.phase3_final_gate_audit import _normalized_config


def test_normalized_config_ignores_only_registered_arm_fields() -> None:
    base = {
        "run_id": "run-a0",
        "policy": "project-continuum-entry-native-lru",
        "trace": "trace.json",
        "backend_options": {
            "phase2g_block_policy": "A0",
            "phase2g_release_policy": "A0",
            "phase3_arm": "A0",
            "cache_block_override": 2048,
        },
    }
    other = {
        **base,
        "run_id": "run-a3",
        "policy": "suffix-cost-entry-native-lru",
        "backend_options": {
            **base["backend_options"],
            "phase2g_release_policy": "A3",
            "phase3_arm": "A3",
        },
    }
    assert _normalized_config(base) == _normalized_config(other)


def test_normalized_config_preserves_non_policy_difference() -> None:
    first = {"backend_options": {"cache_block_override": 2048}}
    second = {"backend_options": {"cache_block_override": 1024}}
    assert _normalized_config(first) != _normalized_config(second)
