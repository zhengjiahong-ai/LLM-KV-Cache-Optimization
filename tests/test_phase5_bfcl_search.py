from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kvopt.workload.phase5_bfcl_search import (
    BFCLSearchError,
    DeterministicSearchReplay,
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
