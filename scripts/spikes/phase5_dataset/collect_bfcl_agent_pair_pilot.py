#!/usr/bin/env python3
"""Run one pinned BFCL SNIPPET/NO_SNIPPET pair against real Tavily search."""

from __future__ import annotations

import argparse
import json
import os
import traceback
import urllib.request
from pathlib import Path

from bfcl_eval.eval_checker.multi_turn_eval.func_source_code.web_search import (
    WebSearchAPI,
)
from bfcl_eval.model_handler import base_handler
from bfcl_eval.model_handler.local_inference.quick_testing_oss import (
    QuickTestingOSSHandler,
)
from bfcl_eval.utils import (
    load_dataset_entry,
    populate_initial_settings_for_web_search_test_cases,
)

from kvopt.workload.phase5_bfcl_agent_bridge import (
    BFCLFrozenSearchBridge,
    InstalledBFCLBridge,
)
from kvopt.workload.phase5_bfcl_search import TavilyFixtureCollector
from kvopt.workload.phase5_dataset_processing import file_sha256
from kvopt.workload.phase5_replay import canonical_sha256

MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
MODEL_REVISION = "d18ecad881a290f0c792f1c2b5dbee1820d4a424"


def _run_inference(
    handler: QuickTestingOSSHandler, test_case: dict[str, object]
) -> dict[str, object]:
    """Invoke only the selected handler without importing BFCL's global registry."""

    try:
        result, metadata = handler.inference(
            test_case, include_input_log=True, exclude_state_log=False
        )
    except Exception as error:  # noqa: BLE001 - preserve BFCL failure evidence
        result = f"Error during inference: {error}"
        metadata = {"traceback": traceback.format_exc()}
    return {"id": test_case["id"], "result": result, **metadata}


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-index", type=int, default=0)
    return parser.parse_args()


def _endpoint_models(base_url: str, api_key: str) -> list[str]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read())
    return [str(row["id"]) for row in payload.get("data", [])]


def main() -> int:
    args = _arguments()
    api_key = os.environ.get("TAVILY_API_KEY", "")
    base_url = os.environ.get("REMOTE_OPENAI_BASE_URL", "")
    endpoint_key = os.environ.get("REMOTE_OPENAI_API_KEY", "EMPTY")
    tokenizer_path = os.environ.get("REMOTE_OPENAI_TOKENIZER_PATH", "")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required")
    if not base_url:
        raise RuntimeError("REMOTE_OPENAI_BASE_URL is required")
    if not tokenizer_path:
        raise RuntimeError("REMOTE_OPENAI_TOKENIZER_PATH is required")
    if MODEL not in _endpoint_models(base_url, endpoint_key):
        raise RuntimeError(f"endpoint does not serve {MODEL}")

    args.output.mkdir(parents=True, exist_ok=False)
    tool_events = args.output / "tool-events.jsonl"
    collector = TavilyFixtureCollector(
        api_key=api_key, archive_root=args.output / "search-evidence"
    )
    bridge = BFCLFrozenSearchBridge(
        collector=collector, event_log_path=tool_events
    )

    selected = []
    for category in ("web_search_base", "web_search_no_snippet"):
        rows = load_dataset_entry(category)
        if not 0 <= args.source_index < len(rows):
            raise RuntimeError("source index is outside the pinned BFCL frame")
        selected.append(rows[args.source_index])
    selected = populate_initial_settings_for_web_search_test_cases(selected)

    handler = QuickTestingOSSHandler(
        model_name=MODEL,
        temperature=0.001,
        registry_name="phase5-bfcl-qwen25-coder-15b",
        is_fc_model=False,
    )
    results = []
    try:
        handler.spin_up_local_server(
            num_gpus=0,
            gpu_memory_utilization=0.0,
            backend="vllm",
            skip_server_setup=True,
            local_model_path=None,
        )
        with InstalledBFCLBridge(
            bridge=bridge,
            web_search_class=WebSearchAPI,
            base_handler_module=base_handler,
        ):
            for test_case in selected:
                results.append(_run_inference(handler, test_case))
    finally:
        handler.shutdown_local_server()

    result_path = args.output / "agent-results.json"
    result_path.write_text(
        json.dumps(results, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )
    events = [json.loads(line) for line in tool_events.read_text().splitlines()]
    expected_ids = [f"web_search_base_{args.source_index}", f"web_search_no_snippet_{args.source_index}"]
    observed_search_ids = {
        event["case_id"]
        for event in events
        if event["event"] == "REAL_SEARCH_ACQUIRED"
    }
    url_fetch_events = [
        event for event in events if event["event"] == "URL_CONTENT_NOT_AUTHORIZED"
    ]
    result_errors = [
        result["id"]
        for result in results
        if isinstance(result.get("result"), str)
        and result["result"].startswith("Error during inference:")
    ]
    blockers = []
    if observed_search_ids != set(expected_ids):
        blockers.append("SEARCH_NOT_OBSERVED_FOR_BOTH_CASES")
    if url_fetch_events:
        blockers.append("URL_CONTENT_REQUESTED_BUT_NOT_AUTHORIZED")
    if result_errors:
        blockers.append("AGENT_INFERENCE_ERROR")
    report = {
        "schema_version": "phase5.bfcl_agent_pair_pilot.v1",
        "status": "PASS" if not blockers else "FAIL_CLOSED",
        "source_index": args.source_index,
        "case_ids": expected_ids,
        "model": MODEL,
        "model_revision": MODEL_REVISION,
        "tool_event_count": len(events),
        "real_search_event_count": sum(
            event["event"] == "REAL_SEARCH_ACQUIRED" for event in events
        ),
        "url_fetch_event_count": len(url_fetch_events),
        "blockers": blockers,
        "result_errors": result_errors,
        "credentials_recorded": False,
        "formal_cohort_selected": False,
        "gpu_execution_authorized": False,
        "agent_results_sha256": file_sha256(result_path),
        "tool_events_sha256": file_sha256(tool_events),
    }
    report["pilot_sha256"] = canonical_sha256(report)
    report_path = args.output / "pilot-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        str(path.relative_to(args.output)): file_sha256(path)
        for path in sorted(args.output.rglob("*"))
        if path.is_file() and path != args.output / "sha256-manifest.json"
    }
    (args.output / "sha256-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
