from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kvopt.workload import continuum_w1b_cost_audit


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_cost_audit_blocks_all_arms_when_agent_prefix_is_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freeze = tmp_path / "freeze.json"
    _write(
        freeze,
        {
            "schema_version": "continuum.w1b_native_smoke_freeze.v1",
            "groups": [
                {
                    "group_id": "g1",
                    "sessions": [
                        {
                            "session_id": "s1",
                            "selected_request_ids": ["s1:1", "s1:2"],
                            "selected_token_counts": [1600, 1800],
                        }
                    ],
                }
            ],
        },
    )
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="utf-8")

    def estimate(token_count: int) -> tuple[float, object]:
        if token_count > 512:
            raise ValueError("unsupported")
        return 0.1, SimpleNamespace(source=SimpleNamespace(value="APPROXIMATED"), reason=None)

    monkeypatch.setattr(
        continuum_w1b_cost_audit,
        "load_prefill_reload_provider",
        lambda _path: SimpleNamespace(estimate=estimate),
    )
    result = continuum_w1b_cost_audit.audit_cost_coverage(
        freeze_path=freeze,
        profile_path=profile,
    )
    assert result["execution_gate"] == "BLOCKED_PREFILL_RELOAD_RANGE"
    assert result["unsupported_query_count"] == 1
    assert set(result["affected_arms"]) == {"A0", "A1", "A2"}
