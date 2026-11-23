from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Self

import pytest

from kvopt.workload.phase5_bfcl_search import (
    BFCLSearchError,
    DeterministicSearchReplay,
    TavilyPageContentCollector,
    search_identity,
)
from kvopt.workload.phase5_replay import canonical_sha256


def _fixture(root: Path, *, query: str) -> None:
    identity = search_identity(query=query, max_results=10, region="wt-wt")
    raw = b'{"results":[]}'
    raw_path = root / "raw" / f"{identity}.json"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(raw)
    raw_sha = hashlib.sha256(raw).hexdigest()
    payload = {
        "schema_version": "phase5.bfcl_search_fixture.v1",
        "fixture_id": canonical_sha256(
            {
                "provider": "TAVILY_SEARCH_API",
                "search_identity": identity,
                "raw_response_sha256": raw_sha,
                "http_status": 200,
                "query": query,
                "max_results": 10,
                "region": "wt-wt",
            }
        ),
        "search_identity": identity,
        "provider": "TAVILY_SEARCH_API",
        "provider_api_version": "TAVILY_HTTP_API_V1",
        "collected_at_utc": "2026-11-21T00:00:00+00:00",
        "query": query,
        "max_results": 10,
        "region": "wt-wt",
        "raw_response_path": f"raw/{identity}.json",
        "raw_response_sha256": raw_sha,
        "results": [
            {
                "rank": 1,
                "title": "Title",
                "url": "https://example.test/source",
                "snippet": "Frozen real snippet",
                "score": 0.9,
            }
        ],
        "error": None,
    }
    path = root / "fixtures" / f"{identity}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_snippet_and_no_snippet_share_raw_fixture(tmp_path: Path) -> None:
    _fixture(tmp_path, query="same query")
    replay = DeterministicSearchReplay(
        fixture_root=tmp_path, call_log_path=tmp_path / "calls.jsonl"
    )
    snippet = replay.search(query="same query", show_snippet=True)
    no_snippet = replay.search(query="same query", show_snippet=False)
    assert snippet == [
        {
            "title": "Title",
            "href": "https://example.test/source",
            "body": "Frozen real snippet",
        }
    ]
    assert no_snippet == [
        {"title": "Title", "href": "https://example.test/source"}
    ]
    events = [
        json.loads(line)
        for line in (tmp_path / "calls.jsonl").read_text().splitlines()
    ]
    assert events[0]["search_identity"] == events[1]["search_identity"]
    assert all(event["network_access"] is False for event in events)


def test_replay_fails_closed_when_fixture_missing(tmp_path: Path) -> None:
    replay = DeterministicSearchReplay(
        fixture_root=tmp_path, call_log_path=tmp_path / "calls.jsonl"
    )
    with pytest.raises(BFCLSearchError, match="no frozen fixture"):
        replay.search(query="unknown", show_snippet=True)


def test_replay_fails_closed_when_raw_response_changes(tmp_path: Path) -> None:
    _fixture(tmp_path, query="same query")
    identity = search_identity(query="same query", max_results=10, region="wt-wt")
    (tmp_path / "raw" / f"{identity}.json").write_text("changed")
    replay = DeterministicSearchReplay(
        fixture_root=tmp_path, call_log_path=tmp_path / "calls.jsonl"
    )
    with pytest.raises(BFCLSearchError, match="SHA-256 mismatch"):
        replay.search(query="same query", show_snippet=False)


class _Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_tavily_page_collector_archives_real_extract_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://example.test/page"
    payload = json.dumps(
        {"results": [{"url": url, "raw_content": "real page body"}]}
    ).encode()
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(payload)
    )
    collector = TavilyPageContentCollector(
        api_key="secret",
        archive_root=tmp_path,
        approved_domains=frozenset({"example.test"}),
    )
    fixture = collector.fetch(url=url)
    assert fixture.error is None
    assert fixture.content == "real page body"
    assert (tmp_path / fixture.raw_response_path).read_bytes() == payload


def test_tavily_page_collector_rejects_unapproved_domain_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    def urlopen(*_args: object, **_kwargs: object) -> _Response:
        nonlocal called
        called = True
        return _Response(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    collector = TavilyPageContentCollector(
        api_key="secret",
        archive_root=tmp_path,
        approved_domains=frozenset({"example.test"}),
    )
    with pytest.raises(BFCLSearchError, match="not approved"):
        collector.fetch(url="https://other.test/page")
    assert called is False
