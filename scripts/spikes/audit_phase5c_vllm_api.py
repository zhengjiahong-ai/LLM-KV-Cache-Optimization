"""Read-only pinned-vLLM API inventory for Phase 5C.

This script imports vLLM but creates no engine and performs no GPU work.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
from pathlib import Path

EXPECTED_VLLM_VERSION = "0.27.1"

METHODS = (
    ("vllm.entrypoints.llm", "LLM.enqueue"),
    ("vllm.entrypoints.llm", "LLM.wait_for_completion"),
    ("vllm.v1.engine.llm_engine", "LLMEngine.add_request"),
    ("vllm.v1.engine.llm_engine", "LLMEngine.step"),
    ("vllm.v1.engine.core_client", "SyncMPClient.get_output"),
    ("vllm.v1.engine.core_client", "AsyncMPClient.get_output_async"),
    ("vllm.v1.engine.core_client", "AsyncMPClient.add_request_async"),
    ("vllm.v1.engine.async_llm", "AsyncLLM.add_request"),
    ("vllm.v1.engine.async_llm", "AsyncLLM._run_output_handler"),
    ("vllm.v1.engine.output_processor", "OutputProcessor.process_outputs"),
    ("vllm.v1.engine.output_processor", "RequestOutputCollector.get"),
    ("vllm.v1.engine.output_processor", "RequestOutputCollector.get_nowait"),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _resolve(root: object, dotted: str) -> object:
    value = root
    for name in dotted.split("."):
        value = getattr(value, name)
    return value


def source_record(module_name: str, dotted_name: str) -> dict[str, object]:
    module = importlib.import_module(module_name)
    value = _resolve(module, dotted_name)
    source = inspect.getsource(value)
    source_file = inspect.getsourcefile(value)
    if source_file is None:
        raise RuntimeError(f"source file unavailable for {module_name}.{dotted_name}")
    path = Path(source_file).resolve()
    return {
        "identity": f"{module_name}.{dotted_name}",
        "signature": str(inspect.signature(value)),
        "source_path": str(path),
        "source_first_line": inspect.getsourcelines(value)[1],
        "method_source_sha256": _sha256(source.encode()),
        "source_file_sha256": _sha256(path.read_bytes()),
    }


def build_report() -> dict[str, object]:
    vllm = importlib.import_module("vllm")
    version = getattr(vllm, "__version__", None)
    if version != EXPECTED_VLLM_VERSION:
        raise RuntimeError(
            f"Phase 5C requires vLLM {EXPECTED_VLLM_VERSION}, observed {version!r}"
        )
    records = [source_record(module, method) for module, method in METHODS]
    return {
        "schema_version": "phase5.vllm_api_source_audit.v1",
        "status": "PASS",
        "vllm_version": version,
        "gpu_execution": False,
        "engine_created": False,
        "methods": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    report = build_report()
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(f"wrote: {output}")
    print(f"sha256: {_sha256(output.read_bytes())}")
    print("PHASE5C_VLLM_API_SOURCE_AUDIT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
