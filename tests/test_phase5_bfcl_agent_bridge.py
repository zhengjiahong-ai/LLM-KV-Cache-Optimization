from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest

from kvopt.workload.phase5_bfcl_agent_bridge import (
    BFCLBridgeError,
    BFCLFrozenSearchBridge,
    InstalledBFCLBridge,
)
from kvopt.workload.phase5_bfcl_pilot_evidence import (
    BFCLPilotEvidenceRecorder,
    load_lifecycle_events,
)


class _Fixture:
    error = None
    fixture_id = "fixture"
    search_identity = "search"
    raw_response_sha256 = "a" * 64
    results = (
        {
            "title": "Title",
            "url": "https://example.test",
            "snippet": "Real snippet",
        },
    )


class _Collector:
    provider = "TEST_PROVIDER"

    def search(self, **_kwargs: object) -> _Fixture:
        return _Fixture()


class _WebSearch:
    show_snippet = True

    def search_engine_query(self, keywords: str) -> list[object]:
        return [keywords]

    def fetch_url_content(self, url: str, mode: str = "raw") -> str:
        return f"{mode}:{url}"


def _base_module() -> ModuleType:
    module = ModuleType("fake_base_handler")

    def execute(
        _calls: list[str],
        _config: dict[str, object],
        _classes: list[str],
        _model: str,
        _case: str,
    ) -> object:
        tool = _WebSearch()
        return tool.search_engine_query("query"), tool.fetch_url_content("https://x")

    module.execute_multi_turn_func_call = execute
    return module


def test_bridge_binds_case_and_rejects_page_fetch(tmp_path: Path) -> None:
    clock = iter(float(value) for value in range(1, 20))
    lifecycle = BFCLPilotEvidenceRecorder(
        path=tmp_path / "lifecycle.jsonl",
        monotonic=lambda: next(clock),
        utc_now=lambda: "2026-11-22T00:00:00Z",
    )
    bridge = BFCLFrozenSearchBridge(
        collector=_Collector(),  # type: ignore[arg-type]
        event_log_path=tmp_path / "events.jsonl",
        lifecycle_recorder=lifecycle,
    )
    module = _base_module()
    original = _WebSearch.search_engine_query
    with lifecycle.bind_case("case-1"), InstalledBFCLBridge(
        bridge=bridge, web_search_class=_WebSearch, base_handler_module=module
    ):
        search, fetch = module.execute_multi_turn_func_call(
            ["search_engine_query(keywords='query')"], {}, [], "m", "case-1"
        )
        assert search[0]["body"] == "Real snippet"
        assert "not authorized" in fetch["error"]
    assert _WebSearch.search_engine_query is original
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [event["case_id"] for event in events] == ["case-1", "case-1"]
    assert events[1]["search_snippet_used_as_page_content"] is False
    lifecycle_events = load_lifecycle_events(tmp_path / "lifecycle.jsonl")
    assert [row["event"] for row in lifecycle_events] == [
        "TOOL_CALL_EMISSION",
        "PROVIDER_REQUEST_DISPATCH",
        "PROVIDER_RESPONSE_COMPLETE",
        "TOOL_RESULT_DELIVERY",
    ]


def test_unbound_tool_call_fails_closed(tmp_path: Path) -> None:
    bridge = BFCLFrozenSearchBridge(
        collector=_Collector(),  # type: ignore[arg-type]
        event_log_path=tmp_path / "events.jsonl",
    )
    with pytest.raises(BFCLBridgeError, match="no bound case identity"):
        bridge.search(query="query", show_snippet=True)


def test_bridge_requires_exactly_one_mode(tmp_path: Path) -> None:
    with pytest.raises(BFCLBridgeError, match="exactly one"):
        BFCLFrozenSearchBridge(event_log_path=tmp_path / "events.jsonl")
