"""Bridge pinned BFCL WebSearchAPI calls to Phase 5 frozen evidence.

The bridge deliberately leaves URL-content retrieval fail-closed. Search snippets
are not page contents and must never be substituted for them.
"""

from __future__ import annotations

import contextvars
import json
import threading
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Self
from urllib.parse import urlparse

from .phase5_bfcl_pilot_evidence import BFCLPilotEvidenceRecorder
from .phase5_bfcl_search import (
    BFCLSearchError,
    DeterministicSearchReplay,
    TavilyFixtureCollector,
)
from .phase5_replay import canonical_sha256

_CURRENT_CASE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "phase5_bfcl_case_id", default=None
)


class BFCLBridgeError(RuntimeError):
    """Raised when the pinned BFCL integration cannot preserve its contract."""


class BFCLFrozenSearchBridge:
    """Serve BFCL search calls in acquisition or deterministic-replay mode."""

    def __init__(
        self,
        *,
        event_log_path: Path,
        collector: TavilyFixtureCollector | None = None,
        replay: DeterministicSearchReplay | None = None,
        lifecycle_recorder: BFCLPilotEvidenceRecorder | None = None,
        approved_page_fetch_domains: frozenset[str] = frozenset(),
    ) -> None:
        if (collector is None) == (replay is None):
            raise BFCLBridgeError("configure exactly one of collector or replay")
        self.collector = collector
        self.replay = replay
        self.event_log_path = event_log_path
        self.lifecycle_recorder = lifecycle_recorder
        self.approved_page_fetch_domains = approved_page_fetch_domains
        self._lock = threading.Lock()
        self._provider_ordinals: Counter[str] = Counter()
        self._tool_batch_ordinals: Counter[str] = Counter()

    @property
    def mode(self) -> str:
        return "REAL_ACQUISITION" if self.collector is not None else "FROZEN_REPLAY"

    def search(
        self,
        *,
        query: str,
        show_snippet: bool,
        max_results: int = 10,
        region: str = "wt-wt",
    ) -> list[dict[str, object]]:
        case_id = _CURRENT_CASE_ID.get()
        if not case_id:
            raise BFCLBridgeError("BFCL search call has no bound case identity")

        if self.collector is not None:
            self._provider_ordinals[case_id] += 1
            provider_request_id = (
                f"{case_id}:provider:{self._provider_ordinals[case_id]}"
            )
            if self.lifecycle_recorder is not None:
                self.lifecycle_recorder.record(
                    "PROVIDER_REQUEST_DISPATCH",
                    provider_request_id=provider_request_id,
                    provider=self.collector.provider,
                    query_sha256=canonical_sha256(query),
                )
            try:
                fixture = self.collector.search(
                    query=query, max_results=max_results, region=region
                )
            except BaseException as error:
                if self.lifecycle_recorder is not None:
                    self.lifecycle_recorder.record(
                        "PROVIDER_REQUEST_FAILED",
                        provider_request_id=provider_request_id,
                        provider=self.collector.provider,
                        error_type=type(error).__name__,
                    )
                raise
            if self.lifecycle_recorder is not None:
                self.lifecycle_recorder.record(
                    "PROVIDER_RESPONSE_COMPLETE",
                    provider_request_id=provider_request_id,
                    provider=self.collector.provider,
                    fixture_id=fixture.fixture_id,
                    raw_response_sha256=fixture.raw_response_sha256,
                )
            if fixture.error is not None:
                raise BFCLSearchError(f"real provider error: {fixture.error}")
            response: list[dict[str, object]] = []
            for result in fixture.results:
                rendered: dict[str, object] = {
                    "title": result["title"],
                    "href": result["url"],
                }
                if show_snippet:
                    rendered["body"] = result["snippet"]
                response.append(rendered)
            self._record(
                {
                    "event": "REAL_SEARCH_ACQUIRED",
                    "case_id": case_id,
                    "query": query,
                    "show_snippet": show_snippet,
                    "fixture_id": fixture.fixture_id,
                    "search_identity": fixture.search_identity,
                    "raw_response_sha256": fixture.raw_response_sha256,
                    "returned_content_sha256": canonical_sha256(response),
                    "network_access": True,
                }
            )
            return response

        assert self.replay is not None
        return self.replay.search(
            query=query,
            show_snippet=show_snippet,
            max_results=max_results,
            region=region,
            case_id=case_id,
        )

    def reject_url_fetch(self, *, url: str, mode: str) -> dict[str, str]:
        case_id = _CURRENT_CASE_ID.get()
        if not case_id:
            raise BFCLBridgeError("BFCL URL fetch has no bound case identity")
        domain = (urlparse(url).hostname or "").lower()
        event = {
            "event": "URL_CONTENT_NOT_AUTHORIZED",
            "case_id": case_id,
            "url": url,
            "url_domain": domain,
            "mode": mode,
            "search_snippet_used_as_page_content": False,
            "approved_page_fetch_domains": sorted(self.approved_page_fetch_domains),
            "domain_approved": domain in self.approved_page_fetch_domains,
        }
        self._record(event)
        return {
            "error": (
                "Phase 5 URL-content acquisition is not authorized; "
                "search snippets were not substituted for page content"
            )
        }

    def _record(self, event: dict[str, object]) -> None:
        payload = {
            "schema_version": "phase5.bfcl_agent_tool_event.v1",
            "bridge_mode": self.mode,
            **event,
        }
        with self._lock:
            self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.event_log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, sort_keys=True) + "\n")


class InstalledBFCLBridge:
    """Reversible patch of the pinned BFCL tool and execution entry point."""

    def __init__(
        self,
        *,
        bridge: BFCLFrozenSearchBridge,
        web_search_class: type,
        base_handler_module: ModuleType,
    ) -> None:
        self.bridge = bridge
        self.web_search_class = web_search_class
        self.base_handler_module = base_handler_module
        self._original_search: Callable[..., Any] | None = None
        self._original_fetch: Callable[..., Any] | None = None
        self._original_execute: Callable[..., Any] | None = None

    def __enter__(self) -> Self:
        if self._original_execute is not None:
            raise BFCLBridgeError("BFCL bridge is already installed")
        self._original_search = self.web_search_class.search_engine_query
        self._original_fetch = self.web_search_class.fetch_url_content
        self._original_execute = self.base_handler_module.execute_multi_turn_func_call
        bridge = self.bridge
        original_execute = self._original_execute

        def search_engine_query(
            instance: object,
            keywords: str,
            max_results: int = 10,
            region: str = "wt-wt",
        ) -> list[dict[str, object]]:
            return bridge.search(
                query=keywords,
                show_snippet=bool(instance.show_snippet),
                max_results=max_results,
                region=region,
            )

        def fetch_url_content(
            _instance: object, url: str, mode: str = "raw"
        ) -> dict[str, str]:
            return bridge.reject_url_fetch(url=url, mode=mode)

        def execute_with_case_identity(
            func_call_list: list[str],
            initial_config: dict[str, object],
            involved_classes: list[str],
            model_name: str,
            test_entry_id: str,
            *args: object,
            **kwargs: object,
        ) -> Any:
            token = _CURRENT_CASE_ID.set(test_entry_id)
            try:
                bridge._tool_batch_ordinals[test_entry_id] += 1
                batch_ordinal = bridge._tool_batch_ordinals[test_entry_id]
                tool_call_ids = [
                    f"{test_entry_id}:tool:{batch_ordinal}:{index}"
                    for index in range(1, len(func_call_list) + 1)
                ]
                if bridge.lifecycle_recorder is not None:
                    for tool_call_id, func_call in zip(
                        tool_call_ids, func_call_list, strict=True
                    ):
                        bridge.lifecycle_recorder.record(
                            "TOOL_CALL_EMISSION",
                            tool_call_id=tool_call_id,
                            tool_call_sha256=canonical_sha256(func_call),
                        )
                try:
                    result = original_execute(
                        func_call_list,
                        initial_config,
                        involved_classes,
                        model_name,
                        test_entry_id,
                        *args,
                        **kwargs,
                    )
                except BaseException as error:
                    if bridge.lifecycle_recorder is not None:
                        bridge.lifecycle_recorder.record(
                            "TOOL_EXECUTION_FAILED",
                            error_type=type(error).__name__,
                        )
                    raise
                if bridge.lifecycle_recorder is not None:
                    execution_results = result[0]
                    if len(execution_results) != len(tool_call_ids):
                        raise BFCLBridgeError(
                            "tool result count differs from emitted call count"
                        )
                    for tool_call_id, execution_result in zip(
                        tool_call_ids, execution_results, strict=True
                    ):
                        bridge.lifecycle_recorder.record(
                            "TOOL_RESULT_DELIVERY",
                            tool_call_id=tool_call_id,
                            tool_result_sha256=canonical_sha256(execution_result),
                        )
                return result
            finally:
                _CURRENT_CASE_ID.reset(token)

        self.web_search_class.search_engine_query = search_engine_query
        self.web_search_class.fetch_url_content = fetch_url_content
        self.base_handler_module.execute_multi_turn_func_call = (
            execute_with_case_identity
        )
        return self

    def __exit__(self, *_exc: object) -> None:
        assert self._original_search is not None
        assert self._original_fetch is not None
        assert self._original_execute is not None
        self.web_search_class.search_engine_query = self._original_search
        self.web_search_class.fetch_url_content = self._original_fetch
        self.base_handler_module.execute_multi_turn_func_call = self._original_execute
        self._original_search = None
        self._original_fetch = None
        self._original_execute = None
