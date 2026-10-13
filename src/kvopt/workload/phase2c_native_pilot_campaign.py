"""Run or resume the frozen 18-run Phase 2C bounded native pilot."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def execute_campaign(
    manifest_path: Path,
    *,
    output_root: Path,
    vllm_metal_source_checkout: Path,
) -> tuple[dict[str, object], Path]:
    manifest_path = manifest_path.resolve()
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    if document.get("schema_version") != "phase2c.native_pilot_materialization.v1":
        raise ValueError("unsupported native-pilot materialization manifest")
    if document.get("run_kind") != "NON_HOLDOUT_NATIVE_PILOT":
        raise ValueError("manifest is not a bounded native pilot")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for position, entry in enumerate(document["runs"], start=1):
        run_id = str(entry["run_id"])
        run_dir = output_root / run_id
        run_manifest = run_dir / "run.json"
        if run_manifest.exists():
            prior = json.loads(run_manifest.read_text(encoding="utf-8"))
            rows.append(
                {
                    "run_id": run_id,
                    "status": "skipped_existing",
                    "execution_status": prior.get("execution_status"),
                    "returncode": None,
                }
            )
            print(f"[{position}/{len(document['runs'])}] {run_id}: skipped_existing")
            continue
        config_path = manifest_path.parent / str(entry["config"])
        command = [
            sys.executable,
            "-m",
            "kvopt.workload.phase2c_native_pilot_runner",
            "--config",
            str(config_path),
            "--output-root",
            str(output_root),
            "--run-id",
            run_id,
        ]
        environment = os.environ.copy()
        environment["VLLM_METAL_SOURCE_CHECKOUT"] = str(vllm_metal_source_checkout.resolve())
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        if run_dir.exists():
            (run_dir / "launcher.stdout.log").write_text(completed.stdout, encoding="utf-8")
            (run_dir / "launcher.stderr.log").write_text(completed.stderr, encoding="utf-8")
        status = "success" if completed.returncode == 0 else "failed"
        rows.append(
            {
                "run_id": run_id,
                "status": status,
                "execution_status": status,
                "returncode": completed.returncode,
            }
        )
        print(f"[{position}/{len(document['runs'])}] {run_id}: {status}")

    summary: dict[str, object] = {
        "schema_version": "phase2c.native_pilot_execution.v1",
        "run_kind": "NON_HOLDOUT_NATIVE_PILOT",
        "materialization_manifest": str(manifest_path),
        "vllm_metal_source_checkout": str(vllm_metal_source_checkout.resolve()),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "planned": len(document["runs"]),
        "success": sum(row["status"] == "success" for row in rows),
        "failed": sum(row["status"] == "failed" for row in rows),
        "skipped": sum(row["status"] == "skipped_existing" for row in rows),
        "runs": rows,
    }
    summary_path = output_root / "execution-summary.json"
    _write_json(summary_path, summary)
    return summary, summary_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--vllm-metal-source-checkout", type=Path, required=True)
    arguments = parser.parse_args(argv)
    summary, path = execute_campaign(
        arguments.manifest,
        output_root=arguments.output_root,
        vllm_metal_source_checkout=arguments.vllm_metal_source_checkout,
    )
    print(
        "Phase 2C native pilot: "
        f"{summary['success']} success, {summary['failed']} failed, "
        f"{summary['skipped']} skipped -> {path}"
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
