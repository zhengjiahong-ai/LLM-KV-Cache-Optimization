"""No-GPU pinned-vLLM request-identity and output-handler interface audit."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import inspect
import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

EXPECTED_VLLM_VERSION = "0.27.1"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_record(value: object, identity: str) -> dict[str, object]:
    source = inspect.getsource(value)
    source_file = inspect.getsourcefile(value)
    if source_file is None:
        raise RuntimeError(f"source file unavailable for {identity}")
    path = Path(source_file).resolve()
    return {
        "identity": identity,
        "signature": str(inspect.signature(value)),
        "source_path": str(path),
        "source_first_line": inspect.getsourcelines(value)[1],
        "method_source_sha256": _sha256(source.encode()),
        "source_file_sha256": _sha256(path.read_bytes()),
        "source": source,
    }


def _call_line(source: str, call_name: str) -> int:
    tree = ast.parse(textwrap.dedent(source))
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = (
            function.attr
            if isinstance(function, ast.Attribute)
            else function.id
            if isinstance(function, ast.Name)
            else None
        )
        if name == call_name:
            lines.append(node.lineno)
    if not lines:
        raise RuntimeError(f"AsyncLLM.add_request lacks call to {call_name}")
    return min(lines)


def build_report() -> dict[str, object]:
    vllm = importlib.import_module("vllm")
    version = getattr(vllm, "__version__", None)
    if version != EXPECTED_VLLM_VERSION:
        raise RuntimeError(
            f"Phase 5D requires vLLM {EXPECTED_VLLM_VERSION}, observed {version!r}"
        )

    envs = importlib.import_module("vllm.envs")
    if envs.VLLM_DISABLE_REQUEST_ID_RANDOMIZATION:
        raise RuntimeError("request ID randomization must remain enabled")

    input_module = importlib.import_module("vllm.v1.engine.input_processor")
    async_module = importlib.import_module("vllm.v1.engine.async_llm")
    output_module = importlib.import_module("vllm.v1.engine.output_processor")
    sampling_module = importlib.import_module("vllm.sampling_params")

    assign = input_module.InputProcessor.assign_request_id
    add_request = async_module.AsyncLLM.add_request
    run_output_handler = async_module.AsyncLLM._run_output_handler
    collector_class = output_module.RequestOutputCollector
    has_request = getattr(output_module.OutputProcessor, "has_request", None)
    abort_requests = output_module.OutputProcessor.abort_requests

    external_id = "phase5d-interface-probe"
    request = SimpleNamespace(request_id=external_id, external_req_id=None)
    assign(request)
    internal_id = request.request_id
    if request.external_req_id != external_id or internal_id == external_id:
        raise RuntimeError("pinned assign_request_id identity semantics changed")

    output_kind = sampling_module.RequestOutputKind.DELTA
    collector = collector_class(output_kind, internal_id)
    if getattr(collector, "request_id", None) != internal_id:
        raise RuntimeError("RequestOutputCollector does not retain internal ID")

    assign_record = _source_record(
        assign, "vllm.v1.engine.input_processor.InputProcessor.assign_request_id"
    )
    add_record = _source_record(
        add_request, "vllm.v1.engine.async_llm.AsyncLLM.add_request"
    )
    handler_record = _source_record(
        run_output_handler,
        "vllm.v1.engine.async_llm.AsyncLLM._run_output_handler",
    )
    if has_request is not None:
        state_query_record = _source_record(
            has_request,
            "vllm.v1.engine.output_processor.OutputProcessor.has_request",
        )
        state_query_source = "HAS_REQUEST_METHOD"
        if "request_id in self.request_states" not in str(
            state_query_record["source"]
        ):
            raise RuntimeError("OutputProcessor internal RequestState query changed")
    else:
        state_query_record = _source_record(
            output_module.OutputProcessor.__init__,
            "vllm.v1.engine.output_processor.OutputProcessor.__init__",
        )
        state_query_source = "REQUEST_STATES_MAPPING"
        if "self.request_states" not in str(state_query_record["source"]):
            raise RuntimeError("OutputProcessor RequestState mapping is unavailable")
    abort_record = _source_record(
        abort_requests,
        "vllm.v1.engine.output_processor.OutputProcessor.abort_requests",
    )
    add_source = str(add_record["source"])
    lifecycle_call_lines = {
        "assign_request_id": _call_line(add_source, "assign_request_id"),
        "run_output_handler": _call_line(add_source, "_run_output_handler"),
        "request_output_collector": _call_line(
            add_source, "RequestOutputCollector"
        ),
    }
    positions = list(lifecycle_call_lines.values())
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise RuntimeError("AsyncLLM.add_request lifecycle ordering changed")
    if "engine_core = self.engine_core" not in str(handler_record["source"]):
        raise RuntimeError("output handler no longer captures EngineCore client")

    abort_source = str(abort_record["source"])
    if "internal" not in abort_source or "external_req_ids" not in abort_source:
        raise RuntimeError("OutputProcessor abort identity routing changed")
    for record in (
        assign_record,
        add_record,
        handler_record,
        state_query_record,
        abort_record,
    ):
        record.pop("source")
    return {
        "schema_version": "phase5d.vllm_identity_interface_audit.v1",
        "status": "PASS",
        "vllm_version": version,
        "gpu_execution": False,
        "engine_created": False,
        "request_id_randomization_enabled": True,
        "external_request_id": external_id,
        "internal_request_id": internal_id,
        "internal_differs_from_external": internal_id != external_id,
        "external_identity_preserved": request.external_req_id == external_id,
        "collector_internal_identity_match": collector.request_id == internal_id,
        "output_handler_capture_contract": "ENGINE_CORE_CAPTURED_AT_HANDLER_START",
        "add_request_lifecycle_call_lines": lifecycle_call_lines,
        "request_state_query_identity": "INTERNAL_REQUEST_ID",
        "request_state_query_source": state_query_source,
        "abort_identity_modes": ["EXTERNAL", "INTERNAL"],
        "methods": [
            assign_record,
            add_record,
            handler_record,
            state_query_record,
            abort_record,
        ],
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
    print("PHASE5D_VLLM_IDENTITY_INTERFACE_AUDIT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
