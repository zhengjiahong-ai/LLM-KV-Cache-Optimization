"""No-GPU pinned-vLLM request-identity and output-handler interface audit."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
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
    has_request = output_module.OutputProcessor.has_request
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
    has_request_record = _source_record(
        has_request, "vllm.v1.engine.output_processor.OutputProcessor.has_request"
    )
    abort_record = _source_record(
        abort_requests,
        "vllm.v1.engine.output_processor.OutputProcessor.abort_requests",
    )
    add_source = str(add_record["source"])
    required_order = (
        "self.input_processor.assign_request_id(request)",
        "self._run_output_handler()",
        "RequestOutputCollector",
    )
    positions = [add_source.find(fragment) for fragment in required_order]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise RuntimeError("AsyncLLM.add_request lifecycle ordering changed")
    if "engine_core = self.engine_core" not in str(handler_record["source"]):
        raise RuntimeError("output handler no longer captures EngineCore client")

    if "request_id in self.request_states" not in str(has_request_record["source"]):
        raise RuntimeError("OutputProcessor internal RequestState query changed")
    abort_source = str(abort_record["source"])
    if "internal" not in abort_source or "external_req_ids" not in abort_source:
        raise RuntimeError("OutputProcessor abort identity routing changed")
    for record in (
        assign_record,
        add_record,
        handler_record,
        has_request_record,
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
        "request_state_query_identity": "INTERNAL_REQUEST_ID",
        "abort_identity_modes": ["EXTERNAL", "INTERNAL"],
        "methods": [
            assign_record,
            add_record,
            handler_record,
            has_request_record,
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
