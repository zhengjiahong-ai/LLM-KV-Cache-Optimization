"""Execute and validate the three-run non-formal H2 intervention check."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

from .phase2_h2_calibration_runner import _run_isolated
from .phase2_h2_intervention_validation import _PROBES
from .phase2_h2_mechanism import (
    _canonical_sha,
    _load_authorization,
    _mechanism_config,
    _trace,
)
from .phase2_h2_mechanism_runner import _validate_direct_evidence


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _return_cached_tokens(directory: Path, probe_id: str) -> int:
    events = [
        json.loads(line)
        for line in (directory / "events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    matches = [
        event
        for event in events
        if event.get("event_type") == "VLLM_NATIVE_REQUEST_OBSERVATION"
        and event.get("request_id") == f"{probe_id}:turn:2"
    ]
    if len(matches) != 1 or not isinstance(matches[0].get("payload"), dict):
        raise ValueError("validation run lacks one native return observation")
    value = matches[0]["payload"].get("native_cached_prefix_tokens")
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("validation run lacks native cached-prefix amount")
    return value


def execute_h2_intervention_validation(
    campaign_path: Path,
    authorization_path: Path,
    output: Path,
) -> tuple[dict[str, object], Path]:
    campaign_path = campaign_path.resolve()
    authorization_path = authorization_path.resolve()
    authorization = _load_authorization(authorization_path)
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    if campaign.get("schema_version") != "phase2a.h2_intervention_validation_campaign.v1":
        raise ValueError("unsupported H2 intervention validation campaign")
    if (
        campaign.get("formal_measurement") is not False
        or campaign.get("formal_verdict") is not False
        or campaign.get("b1_authorized") is not False
    ):
        raise ValueError("intervention validation must remain non-formal")
    if campaign.get("authorization_sha256") != _sha(authorization_path):
        raise ValueError("intervention validation authorization hash mismatch")
    probes = campaign.get("probes")
    if not isinstance(probes, list) or len(probes) != len(_PROBES):
        raise ValueError("intervention validation requires the frozen probe set")
    campaign_dir = campaign_path.parent
    selected: list[tuple[Path, dict[str, object]]] = []
    for probe, frozen in zip(probes, _PROBES, strict=True):
        if not isinstance(probe, dict) or any(
            probe.get(field) != value for field, value in frozen.items()
        ):
            raise ValueError("intervention validation probe differs from frozen design")
        config_path = (campaign_dir / str(probe.get("config"))).resolve()
        if config_path.parent != campaign_dir or _sha(config_path) != probe.get(
            "config_file_sha256"
        ):
            raise ValueError("intervention validation config hash mismatch")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        probe_id = str(probe["probe_id"])
        expected_config = _mechanism_config(
            authorization,
            probe_id=probe_id,
            prefix_tokens=int(probe["prefix_tokens"]),
            trace_name=f"{probe_id}.trace.json",
            position=probe["position"],  # type: ignore[arg-type]
            count=int(probe["evicted_blocks"]),
            campaign_kind="h2_intervention_validation",
        )
        expected_config["h2_measurement"] = {
            **expected_config["h2_measurement"],  # type: ignore[misc]
            "formal_measurement": False,
            "validation_only": True,
        }
        if config != expected_config or _canonical_sha(config) != probe.get(
            "runtime_config_sha256"
        ):
            raise ValueError("intervention validation config differs from design")
        trace_path = (campaign_dir / str(config.get("trace"))).resolve()
        if trace_path.parent != campaign_dir or _sha(trace_path) != probe.get(
            "trace_sha256"
        ):
            raise ValueError("intervention validation trace hash mismatch")
        if json.loads(trace_path.read_text(encoding="utf-8")) != _trace(
            probe_id,
            int(probe["prefix_tokens"]),
        ).to_dict():
            raise ValueError("intervention validation trace differs from design")
        selected.append((config_path, probe))
    output = output.resolve()
    if any((output / str(probe["run_id"])).exists() for _, probe in selected):
        raise FileExistsError("validation output already exists; use a new output root")
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for config_path, probe in selected:
        run_id = str(probe["run_id"])
        directory = _run_isolated(config_path, output, run_id)
        manifest = json.loads(
            (directory / "run.json").read_text(encoding="utf-8")
        )
        if manifest.get("status") != "success":
            raise ValueError(f"validation run failed; preserve evidence: {run_id}")
        if manifest.get("config_sha256") != probe["runtime_config_sha256"]:
            raise ValueError("validation run config provenance mismatch")
        if manifest.get("trace_sha256") != probe["trace_sha256"]:
            raise ValueError("validation run trace provenance mismatch")
        _validate_direct_evidence(directory, probe)
        observed = _return_cached_tokens(directory, str(probe["probe_id"]))
        expected = probe["expected_cached_prefix_tokens"]
        if observed != expected:
            raise ValueError(
                f"validation cached-prefix mismatch for {run_id}: "
                f"expected {expected}, observed {observed}"
            )
        results.append(
            {
                "run_id": run_id,
                "status": "success",
                "expected_cached_prefix_tokens": expected,
                "observed_cached_prefix_tokens": observed,
                "run_directory": str(directory),
            }
        )
        print(f"{run_id}: success ({observed} cached tokens)", flush=True)
    summary = {
        "schema_version": "phase2a.h2_intervention_validation_execution.v1",
        "campaign_sha256": _sha(campaign_path),
        "formal_measurement": False,
        "formal_verdict": False,
        "b1_authorized": False,
        "successful_run_count": len(results),
        "results": results,
    }
    path = output / f"intervention-validation-{uuid.uuid4().hex[:12]}.json"
    path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary, path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--vllm-metal-source-checkout", type=Path, required=True)
    args = parser.parse_args()
    os.environ.update(
        VLLM_ENABLE_V1_MULTIPROCESSING="0",
        VLLM_METAL_USE_PAGED_ATTENTION="1",
        VLLM_METAL_MEMORY_FRACTION="auto",
        VLLM_MLX_DEVICE="gpu",
        VLLM_HOST_IP="127.0.0.1",
        VLLM_METAL_SOURCE_CHECKOUT=str(
            args.vllm_metal_source_checkout.resolve()
        ),
    )
    summary, path = execute_h2_intervention_validation(
        args.campaign,
        args.authorization,
        args.output_root,
    )
    print(
        f"H2 intervention validation: {summary['successful_run_count']} success "
        f"-> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
