import json
from pathlib import Path

from kvopt.workload import phase2b_runner
from kvopt.workload.phase2b_fidelity_runner import RequestCompletion, RequestHandle


class _Backend:
    phase2b_supported_capabilities = (
        "prefix_content_identity",
        "true_request_overlap",
    )

    def __init__(self) -> None:
        self.pending: dict[str, RequestHandle] = {}
        self.forced_release_count = 0
        self.closed = False

    def submit(self, request):
        handle = RequestHandle(
            request.request_id,
            f"native-{request.request_id}",
            f"external-{request.request_id}",
            1.0,
        )
        self.pending[request.request_id] = handle
        return handle

    def collect_completed(self, *, until=None):
        return ()

    def drain(self, *, timeout_seconds):
        rows = tuple(
            RequestCompletion(
                logical_request_id=handle.logical_request_id,
                native_request_id=handle.native_request_id,
                external_request_id=handle.external_request_id,
                completed_at=2.0,
            )
            for handle in self.pending.values()
        )
        self.pending.clear()
        return rows

    def close(self):
        self.closed = True


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_phase2b_runner_separates_execution_from_pending_native_gates(
    tmp_path: Path, monkeypatch
) -> None:
    _write(
        tmp_path / "trace.json",
        {
            "schema_version": "phase2.trace.v1",
            "trace_id": "fixture",
            "requests": [
                {
                    "program_id": program,
                    "request_id": f"{program}:1",
                    "turn_index": 1,
                    "planned_arrival_offset_seconds": 0,
                    "prompt": "p",
                    "prefix_prompt": "x",
                    "is_terminal": True,
                    "next_tool_type": None,
                    "tool_gap_seconds": None,
                }
                for program in ("a", "b")
            ],
            "pressure_stages": [],
        },
    )
    _write(
        tmp_path / "contract.json",
        {
            "schema_version": "phase2b.fidelity_contract.v1",
            "run_kind": "NON_HOLDOUT_FIDELITY_REPAIR",
            "case_id": "AR-S1",
            "required_capabilities": [
                "prefix_content_identity",
                "true_request_overlap",
            ],
            "constraints": {"max_in_flight": 2, "timeout_seconds": 5},
        },
    )
    config = {
        "schema_version": "phase2.config.v1",
        "trace": "trace.json",
        "fidelity_contract": "contract.json",
        "seed": 1,
        "policy": "continuum-baseline",
        "runtime_mode": "fake",
        "backend_factory": "fake:factory",
        "backend_revision": "fake-v1",
        "model": {"name": "fake", "revision": "1"},
        "tokenizer": {"name": "fake", "revision": "1"},
        "cache": {"block_override": 8, "block_size": 16},
        "generation": {},
        "batching": {"max_concurrent_requests": 2},
        "pressure": {"safety_ceiling": 1},
        "backend_options": {
            "phase2b_fidelity_mode": True,
            "prefix_generator_version": "phase2b-prefix-v1",
            "prefix_content_key_by_program": {"a": "shared", "b": "shared"},
            "program_prefix_tokens": {"a": 16, "b": 16},
            "executor_mode": "submit_collect",
        },
    }
    _write(tmp_path / "config.json", config)
    backend = _Backend()
    monkeypatch.setattr(phase2b_runner, "_load_factory", lambda _value: lambda *_: backend)

    output = phase2b_runner.run_phase2b_fidelity(
        tmp_path / "config.json",
        output_root=tmp_path / "out",
        run_id="test-run",
    )

    manifest = json.loads((output / "run.json").read_text(encoding="utf-8"))
    result = json.loads(
        (output / "fidelity-result.json").read_text(encoding="utf-8")
    )
    assert manifest["execution_status"] == "success"
    assert manifest["fidelity_qualification"] == "NOT_DEMONSTRATED"
    assert result["gates"][0]["gate"] == "G-INFLIGHT"
    assert result["gates"][0]["status"] == "PASS"
    assert backend.closed is True
