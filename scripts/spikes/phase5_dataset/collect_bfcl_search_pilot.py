"""Collect one real Tavily response and verify deterministic local replay."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from kvopt.workload.phase5_bfcl_search import (
    DeterministicSearchReplay,
    TavilyFixtureCollector,
)
from kvopt.workload.phase5_dataset_processing import file_sha256
from kvopt.workload.phase5_replay import canonical_sha256


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-results", type=int, default=10)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("output already exists; acquisition evidence is immutable")
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured")

    collector = TavilyFixtureCollector(api_key=api_key, archive_root=args.output)
    fixture = collector.search(query=args.query, max_results=args.max_results)
    replay = DeterministicSearchReplay(
        fixture_root=args.output,
        call_log_path=args.output / "replay-events.jsonl",
    )
    snippet = replay.search(query=args.query, show_snippet=True)
    no_snippet = replay.search(query=args.query, show_snippet=False)
    if fixture.error is not None:
        raise RuntimeError(f"provider returned a frozen error: {fixture.error}")
    if not fixture.results:
        raise RuntimeError("provider returned no search results")
    if len(snippet) != len(no_snippet):
        raise RuntimeError("SNIPPET/NO_SNIPPET result counts differ")
    if any("body" not in result for result in snippet):
        raise RuntimeError("SNIPPET replay omitted snippet content")
    if any("body" in result for result in no_snippet):
        raise RuntimeError("NO_SNIPPET replay exposed snippet content")

    payload: dict[str, object] = {
        "schema_version": "phase5.bfcl_search_pilot.v1",
        "status": "PASS",
        "provider": fixture.provider,
        "query": args.query,
        "fixture_id": fixture.fixture_id,
        "search_identity": fixture.search_identity,
        "raw_response_sha256": fixture.raw_response_sha256,
        "result_count": len(fixture.results),
        "snippet_response_sha256": canonical_sha256(snippet),
        "no_snippet_response_sha256": canonical_sha256(no_snippet),
        "shared_raw_identity": True,
        "replay_network_access": False,
        "credentials_recorded": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
    }
    report = {**payload, "pilot_sha256": canonical_sha256(payload)}
    _write(args.output / "pilot-report.json", report)
    files = [
        path
        for path in args.output.rglob("*")
        if path.is_file() and path.name != "sha256-manifest.json"
    ]
    _write(
        args.output / "sha256-manifest.json",
        {
            "schema_version": "phase5.dataset_sha256_manifest.v1",
            "files": [
                {
                    "path": path.relative_to(args.output).as_posix(),
                    "sha256": file_sha256(path),
                }
                for path in sorted(files)
            ],
        },
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
