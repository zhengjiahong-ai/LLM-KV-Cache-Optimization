"""Execute the authorized formal H2 M2/M3 campaign in isolated processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .phase2_h2_calibration_runner import _run_isolated
from .phase2_h2_mechanism import (
    _M2_PREFIX_BLOCKS,
    _M2_RETAINED_BLOCKS,
    _M3_EVICTED_BLOCKS,
    _M3_PREFIX_TOKENS,
    _MEASUREMENTS,
    _WARMUPS,
    _canonical_sha,
    _load_authorization,
    _mechanism_config,
    _trace,
)

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_probes() -> list[dict[str, object]]:
    probes: list[dict[str, object]] = []
    for retained in _M2_RETAINED_BLOCKS:
        control = (
            "full-evict"
            if retained == 0
            else "full-retain"
            if retained == _M2_PREFIX_BLOCKS
            else None
        )
        probes.append(
            {
                "probe_id": f"m2-k{retained}",
                "measurement": "M2",
                "prefix_tokens": _M2_PREFIX_BLOCKS * 16,
                "position": "trailing",
                "evicted_blocks": _M2_PREFIX_BLOCKS - retained,
                "retained_leading_blocks": retained,
                "control": control,
            }
        )
    probes.append(
        {
            "probe_id": "m2-no-eviction-control",
            "measurement": "M2",
            "prefix_tokens": _M2_PREFIX_BLOCKS * 16,
            "position": None,
            "evicted_blocks": 0,
            "retained_leading_blocks": _M2_PREFIX_BLOCKS,
            "control": "no-eviction-full-hit",
        }
    )
    for prefix_tokens in _M3_PREFIX_TOKENS:
        for count in _M3_EVICTED_BLOCKS:
            for position in ("leading", "trailing"):
                probes.append(
                    {
                        "probe_id": f"m3-r{prefix_tokens}-j{count}-{position}",
                        "measurement": "M3",
                        "prefix_tokens": prefix_tokens,
                        "position": position,
                        "evicted_blocks": count,
                        "cell_id": f"m3-r{prefix_tokens}-j{count}",
                    }
                )
    return probes


def _inside_campaign(campaign_dir: Path, name: object, field: str) -> Path:
    if not isinstance(name, str) or not name:
        raise TypeError(f"formal {field} must be a filename")
    path = (campaign_dir / name).resolve()
    if path.parent != campaign_dir:
        raise ValueError(f"formal {field} must be inside campaign directory")
    return path


def _validate_campaign(
    campaign_path: Path,
    authorization_path: Path,
) -> tuple[dict[str, Any], str, list[tuple[Path, dict[str, Any], dict[str, str]]]]:
    campaign_path = campaign_path.resolve()
    authorization_path = authorization_path.resolve()
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    authorization = _load_authorization(authorization_path)
    if campaign.get("schema_version") != "phase2a.h2_formal_m2_m3_campaign.v1":
        raise ValueError("unsupported formal M2/M3 campaign")
    authorization_sha = _sha(authorization_path)
    if campaign.get("authorization_sha256") != authorization_sha:
        raise ValueError("campaign authorization hash mismatch")
    if campaign.get("formal_measurement") is not True:
        raise ValueError("campaign must declare formal measurement")
    if campaign.get("formal_verdict_authorized") is not False:
        raise ValueError("formal verdict must await data validation")
    if campaign.get("b1_authorized") is not False:
        raise ValueError("B1 must remain unauthorized")
    probes = campaign.get("probes")
    expected = _expected_probes()
    if not isinstance(probes, list) or len(probes) != len(expected):
        raise ValueError("formal M2/M3 probe count mismatch")
    if (
        campaign.get("probe_count") != 30
        or campaign.get("m2_probe_count") != 6
        or campaign.get("m3_arm_count") != 24
        or campaign.get("m3_cell_count") != 12
    ):
        raise ValueError("formal M2/M3 campaign dimensions mismatch")
    selected: list[tuple[Path, dict[str, Any], dict[str, str]]] = []
    seen_run_ids: set[str] = set()
    campaign_dir = campaign_path.parent
    roles = ["warmup"] * _WARMUPS + ["measured"] * _MEASUREMENTS
    for probe, frozen in zip(probes, expected, strict=True):
        if not isinstance(probe, dict):
            raise TypeError("formal probe must be an object")
        for field, value in frozen.items():
            if probe.get(field) != value:
                raise ValueError(f"formal probe differs from frozen {field}")
        probe_id = frozen["probe_id"]
        assert isinstance(probe_id, str)
        config_path = _inside_campaign(campaign_dir, probe.get("config"), "configuration")
        if config_path.name != f"{probe_id}.config.json":
            raise ValueError("formal configuration filename mismatch")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        expected_config = _mechanism_config(
            authorization,
            probe_id=probe_id,
            prefix_tokens=int(frozen["prefix_tokens"]),
            trace_name=f"{probe_id}.trace.json",
            position=frozen["position"],  # type: ignore[arg-type]
            count=int(frozen["evicted_blocks"]),
        )
        if config != expected_config:
            raise ValueError("formal mechanism configuration differs from authorization")
        if _canonical_sha(config) != probe.get("runtime_config_sha256"):
            raise ValueError("formal mechanism runtime config hash mismatch")
        if _sha(config_path) != probe.get("config_file_sha256"):
            raise ValueError("formal mechanism config file hash mismatch")
        trace_path = _inside_campaign(campaign_dir, config.get("trace"), "trace")
        if json.loads(trace_path.read_text(encoding="utf-8")) != _trace(
            probe_id,
            int(frozen["prefix_tokens"]),
        ).to_dict():
            raise ValueError("formal mechanism trace differs from frozen trace")
        if _sha(trace_path) != probe.get("trace_sha256"):
            raise ValueError("formal mechanism trace hash mismatch")
        runs = probe.get("runs")
        if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
            raise TypeError("formal probe runs must be objects")
        if [run.get("role") for run in runs] != roles:
            raise ValueError("formal repetitions must be 2 warmups and 9 measured")
        for run in runs:
            run_id = run.get("run_id")
            role = run.get("role")
            if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
                raise ValueError("unsafe formal run ID")
            if run_id in seen_run_ids:
                raise ValueError("duplicate formal run ID")
            seen_run_ids.add(run_id)
            selected.append((config_path, probe, {"run_id": run_id, "role": role}))
    if len(selected) != 330 or campaign.get("planned_run_count") != 330:
        raise ValueError("formal M2/M3 campaign requires 330 runs")
    return campaign, authorization_sha, selected


def _validate_direct_evidence(
    directory: Path,
    probe: dict[str, Any],
) -> None:
    events_path = directory / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    interventions = [
        event for event in events
        if event.get("event_type") == "H2_NATIVE_PREFIX_INTERVENTION"
    ]
    position = probe["position"]
    expected_count = 0 if position is None else 1
    if len(interventions) != expected_count:
        raise ValueError("formal run intervention evidence count mismatch")
    if interventions:
        event = interventions[0]
        payload = event.get("payload")
        if (
            event.get("request_id") != f"{probe['probe_id']}:turn:1"
            or not isinstance(payload, dict)
            or payload.get("position") != position
            or payload.get("count") != probe["evicted_blocks"]
            or payload.get("ownership_changed") is not False
            or payload.get("queue_reordered") is not False
        ):
            raise ValueError("formal run intervention evidence differs from probe")
    returns = [
        event for event in events
        if event.get("event_type") == "VLLM_NATIVE_REQUEST_OBSERVATION"
        and event.get("request_id") == f"{probe['probe_id']}:turn:2"
    ]
    if len(returns) != 1 or not isinstance(returns[0].get("payload"), dict):
        raise ValueError("formal run lacks one direct native return observation")
    payload = returns[0]["payload"]
    prompt_tokens = payload.get("native_prompt_tokens")
    cached_tokens = payload.get("native_cached_prefix_tokens")
    if (
        prompt_tokens != probe["prefix_tokens"] + 1
        or isinstance(cached_tokens, bool)
        or not isinstance(cached_tokens, int)
        or not 0 <= cached_tokens <= probe["prefix_tokens"]
    ):
        raise ValueError("formal run return token evidence is invalid")


def execute_formal_m2_m3(
    campaign_path: Path,
    authorization_path: Path,
    output: Path,
    *,
    resume: bool = False,
) -> tuple[dict[str, object], Path]:
    campaign_path = campaign_path.resolve()
    campaign, authorization_sha, selected = _validate_campaign(
        campaign_path,
        authorization_path,
    )
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        [
            "git", "status", "--porcelain", "--untracked-files=normal", "--",
            "src", "scripts", "configs",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise ValueError("commit source/config changes before formal execution")
    output = output.resolve()
    if not resume and any((output / run["run_id"]).exists() for _, _, run in selected):
        raise FileExistsError("formal run already exists; use resume for validated successes")
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for index, (config_path, probe, run) in enumerate(selected, 1):
        run_id = run["run_id"]
        directory = output / run_id
        existing = directory.exists()
        if not existing:
            directory = _run_isolated(config_path, output, run_id)
        manifest = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        if manifest.get("status") != "success":
            raise ValueError(f"formal run failed; preserve evidence: {run_id}")
        if manifest.get("git_sha") != git_sha or manifest.get("git_dirty") is not False:
            raise ValueError(f"formal run code provenance mismatch: {run_id}")
        if manifest.get("config_sha256") != probe["runtime_config_sha256"]:
            raise ValueError(f"formal run config provenance mismatch: {run_id}")
        if manifest.get("trace_sha256") != probe["trace_sha256"]:
            raise ValueError(f"formal run trace provenance mismatch: {run_id}")
        _validate_direct_evidence(directory, probe)
        status = "skipped_existing" if existing else "success"
        results.append(
            {
                **run,
                "probe_id": probe["probe_id"],
                "measurement": probe["measurement"],
                "status": status,
                "run_directory": str(directory),
            }
        )
        print(f"[{index}/330] {run_id}: {status}", flush=True)
    summary = {
        "schema_version": "phase2a.h2_formal_m2_m3_execution.v1",
        "campaign_id": campaign.get("campaign_id"),
        "git_sha": git_sha,
        "authorization_sha256": authorization_sha,
        "campaign_sha256": _sha(campaign_path),
        "formal_measurement": True,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "successful_run_count": sum(row["status"] == "success" for row in results),
        "skipped_run_count": sum(
            row["status"] == "skipped_existing" for row in results
        ),
        "results": results,
    }
    path = output / f"formal-m2-m3-execution-{uuid.uuid4().hex[:12]}.json"
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
    parser.add_argument("--resume", action="store_true")
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
    summary, path = execute_formal_m2_m3(
        args.campaign,
        args.authorization,
        args.output_root,
        resume=args.resume,
    )
    print(
        f"formal H2 M2/M3 complete: {summary['successful_run_count']} success, "
        f"{summary['skipped_run_count']} skipped -> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
