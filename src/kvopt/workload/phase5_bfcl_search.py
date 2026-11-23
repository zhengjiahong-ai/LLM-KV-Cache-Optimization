"""Real BFCL search acquisition and deterministic frozen replay."""

from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .phase5_dataset_processing import file_sha256
from .phase5_replay import canonical_sha256


class BFCLSearchError(RuntimeError):
    """Raised when real acquisition or frozen replay cannot be proven."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def search_identity(*, query: str, max_results: int, region: str) -> str:
    """Return the provider-independent identity for one search request."""

    return canonical_sha256(
        {"query": query, "max_results": max_results, "region": region}
    )


@dataclass(frozen=True)
class FrozenSearchFixture:
    fixture_id: str
    search_identity: str
    provider: str
    provider_api_version: str
    collected_at_utc: str
    query: str
    max_results: int
    region: str
    raw_response_path: str
    raw_response_sha256: str
    results: tuple[dict[str, Any], ...]
    error: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5.bfcl_search_fixture.v1",
            "fixture_id": self.fixture_id,
            "search_identity": self.search_identity,
            "provider": self.provider,
            "provider_api_version": self.provider_api_version,
            "collected_at_utc": self.collected_at_utc,
            "query": self.query,
            "max_results": self.max_results,
            "region": self.region,
            "raw_response_path": self.raw_response_path,
            "raw_response_sha256": self.raw_response_sha256,
            "results": list(self.results),
            "error": self.error,
        }


class TavilyFixtureCollector:
    """Call Tavily once per unique query and preserve byte-exact responses."""

    provider = "TAVILY_SEARCH_API"
    api_version = "TAVILY_HTTP_API_V1"

    def __init__(self, *, api_key: str, archive_root: Path) -> None:
        if not api_key:
            raise BFCLSearchError("TAVILY_API_KEY is required")
        self._api_key = api_key
        self.archive_root = archive_root
        self._lock = threading.Lock()
        self._fixtures: dict[str, FrozenSearchFixture] = {}

    def search(
        self, *, query: str, max_results: int = 10, region: str = "wt-wt"
    ) -> FrozenSearchFixture:
        identity = search_identity(
            query=query, max_results=max_results, region=region
        )
        with self._lock:
            existing = self._fixtures.get(identity)
            if existing is not None:
                return existing

        request_payload = {
            "query": query,
            "search_depth": "basic",
            "topic": "general",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
        request = urllib.request.Request(
            "https://api.tavily.com/search",
            data=_canonical_json_bytes(request_payload),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        collected_at = datetime.now(timezone.utc).isoformat()
        error: str | None = None
        status_code: int | None = None
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status_code = response.status
                raw = response.read()
        except urllib.error.HTTPError as http_error:
            status_code = http_error.code
            raw = http_error.read()
            error = f"HTTP_{http_error.code}"
        except (OSError, urllib.error.URLError) as network_error:
            raw = _canonical_json_bytes({"network_error": str(network_error)})
            error = type(network_error).__name__

        raw_sha = hashlib.sha256(raw).hexdigest()
        raw_relative = f"raw/{identity}.json"
        raw_path = self.archive_root / raw_relative
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path.exists():
            if file_sha256(raw_path) != raw_sha:
                raise BFCLSearchError("immutable raw response identity collision")
        else:
            raw_path.write_bytes(raw)

        results: list[dict[str, Any]] = []
        if error is None:
            try:
                payload = json.loads(raw)
                for rank, result in enumerate(payload.get("results", []), start=1):
                    results.append(
                        {
                            "rank": rank,
                            "title": str(result.get("title", "")),
                            "url": str(result.get("url", "")),
                            "snippet": str(result.get("content", "")),
                            "score": result.get("score"),
                        }
                    )
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as decode:
                error = f"INVALID_PROVIDER_RESPONSE:{type(decode).__name__}"
        fixture_payload = {
            "provider": self.provider,
            "api_version": self.api_version,
            "search_identity": identity,
            "raw_response_sha256": raw_sha,
            "http_status": status_code,
            "query": query,
            "max_results": max_results,
            "region": region,
        }
        fixture = FrozenSearchFixture(
            fixture_id=canonical_sha256(fixture_payload),
            search_identity=identity,
            provider=self.provider,
            provider_api_version=self.api_version,
            collected_at_utc=collected_at,
            query=query,
            max_results=max_results,
            region=region,
            raw_response_path=raw_relative,
            raw_response_sha256=raw_sha,
            results=tuple(results),
            error=error,
        )
        fixture_path = self.archive_root / "fixtures" / f"{identity}.json"
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = _canonical_json_bytes(fixture.to_dict()) + b"\n"
        if fixture_path.exists() and fixture_path.read_bytes() != serialized:
            raise BFCLSearchError("immutable normalized fixture identity collision")
        fixture_path.write_bytes(serialized)
        with self._lock:
            self._fixtures[identity] = fixture
        return fixture


@dataclass(frozen=True)
class FrozenPageFixture:
    fixture_id: str
    provider: str
    provider_api_version: str
    collected_at_utc: str
    url: str
    domain: str
    mode: str
    raw_response_path: str
    raw_response_sha256: str
    content: str | None
    error: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "phase5.bfcl_page_fixture.v1",
            **self.__dict__,
        }


class TavilyPageContentCollector:
    """Acquire one approved page through Tavily Extract without retry/fallback."""

    provider = "TAVILY_EXTRACT_API"
    api_version = "TAVILY_HTTP_API_V1"

    def __init__(
        self,
        *,
        api_key: str,
        archive_root: Path,
        approved_domains: frozenset[str],
    ) -> None:
        if not api_key:
            raise BFCLSearchError("TAVILY_API_KEY is required")
        if not approved_domains:
            raise BFCLSearchError("approved page-fetch domains are required")
        self._api_key = api_key
        self.archive_root = archive_root
        self.approved_domains = approved_domains
        self._lock = threading.Lock()
        self._fixtures: dict[str, FrozenPageFixture] = {}

    def fetch(self, *, url: str, mode: str = "raw") -> FrozenPageFixture:
        domain = (urlparse(url).hostname or "").lower()
        if domain not in self.approved_domains:
            raise BFCLSearchError(f"page-fetch domain is not approved: {domain}")
        identity = canonical_sha256(
            {
                "provider": self.provider,
                "api_version": self.api_version,
                "url": url,
                "mode": mode,
            }
        )
        with self._lock:
            prior = self._fixtures.get(identity)
            if prior is not None:
                return prior

        request = urllib.request.Request(
            "https://api.tavily.com/extract",
            data=_canonical_json_bytes(
                {
                    "urls": [url],
                    "extract_depth": "basic",
                    "include_images": False,
                }
            ),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        collected_at = datetime.now(timezone.utc).isoformat()
        error: str | None = None
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as http_error:
            raw = http_error.read()
            error = f"HTTP_{http_error.code}"
        except (OSError, urllib.error.URLError) as network_error:
            raw = _canonical_json_bytes({"network_error": str(network_error)})
            error = type(network_error).__name__

        raw_sha = hashlib.sha256(raw).hexdigest()
        raw_relative = f"page-raw/{identity}.json"
        raw_path = self.archive_root / raw_relative
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        if raw_path.exists():
            if file_sha256(raw_path) != raw_sha:
                raise BFCLSearchError("immutable page response identity collision")
        else:
            raw_path.write_bytes(raw)

        content: str | None = None
        if error is None:
            try:
                payload = json.loads(raw)
                matches = [
                    row
                    for row in payload.get("results", [])
                    if row.get("url") == url
                ]
                failures = [
                    row
                    for row in payload.get("failed_results", [])
                    if row.get("url") == url
                ]
                if len(matches) == 1 and isinstance(
                    matches[0].get("raw_content"), str
                ):
                    extracted = matches[0]["raw_content"]
                    if extracted.strip():
                        content = extracted
                    else:
                        error = "EXTRACT_EMPTY_CONTENT"
                elif failures:
                    error = f"EXTRACT_FAILED:{failures[0].get('error', 'UNKNOWN')}"
                else:
                    error = "EXTRACT_RESULT_MISSING"
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as decode:
                error = f"INVALID_EXTRACT_RESPONSE:{type(decode).__name__}"
        fixture_payload = {
            "provider": self.provider,
            "api_version": self.api_version,
            "url": url,
            "mode": mode,
            "raw_response_sha256": raw_sha,
        }
        fixture = FrozenPageFixture(
            fixture_id=canonical_sha256(fixture_payload),
            provider=self.provider,
            provider_api_version=self.api_version,
            collected_at_utc=collected_at,
            url=url,
            domain=domain,
            mode=mode,
            raw_response_path=raw_relative,
            raw_response_sha256=raw_sha,
            content=content,
            error=error,
        )
        fixture_path = self.archive_root / "page-fixtures" / f"{identity}.json"
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = _canonical_json_bytes(fixture.to_dict()) + b"\n"
        if fixture_path.exists() and fixture_path.read_bytes() != serialized:
            raise BFCLSearchError("immutable page fixture identity collision")
        fixture_path.write_bytes(serialized)
        with self._lock:
            self._fixtures[identity] = fixture
        return fixture


class DeterministicSearchReplay:
    """Serve frozen results without network access and record every call."""

    def __init__(self, *, fixture_root: Path, call_log_path: Path) -> None:
        self.fixture_root = fixture_root
        self.call_log_path = call_log_path
        self._lock = threading.Lock()

    def search(
        self,
        *,
        query: str,
        show_snippet: bool,
        max_results: int = 10,
        region: str = "wt-wt",
        logical_time_seconds: float | None = None,
        case_id: str | None = None,
    ) -> list[dict[str, object]]:
        identity = search_identity(
            query=query, max_results=max_results, region=region
        )
        fixture_path = self.fixture_root / "fixtures" / f"{identity}.json"
        if not fixture_path.is_file():
            raise BFCLSearchError(f"no frozen fixture for search identity {identity}")
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        if fixture["search_identity"] != identity:
            raise BFCLSearchError("fixture search identity mismatch")
        raw_path = self.fixture_root / fixture["raw_response_path"]
        if not raw_path.is_file():
            raise BFCLSearchError("fixture raw response is missing")
        if file_sha256(raw_path) != fixture["raw_response_sha256"]:
            raise BFCLSearchError("fixture raw response SHA-256 mismatch")
        if fixture["error"] is not None:
            raise BFCLSearchError(f"frozen provider error: {fixture['error']}")

        response = []
        for result in fixture["results"]:
            rendered: dict[str, object] = {
                "title": result["title"],
                "href": result["url"],
            }
            if show_snippet:
                rendered["body"] = result["snippet"]
            response.append(rendered)
        response_sha = canonical_sha256(response)
        event = {
            "schema_version": "phase5.bfcl_search_replay_event.v1",
            "query": query,
            "show_snippet": show_snippet,
            "search_identity": identity,
            "fixture_id": fixture["fixture_id"],
            "returned_content_sha256": response_sha,
            "replay": True,
            "network_access": False,
            "logical_time_seconds": logical_time_seconds,
            "case_id": case_id,
            "latency_semantics": "LOCAL_REPLAY_NOT_REAL_NETWORK_LATENCY",
        }
        with self._lock:
            self.call_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.call_log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, sort_keys=True) + "\n")
        return response
