"""Validate pinned BFCL inputs and external acquisition prerequisites."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from kvopt.workload.phase5_bfcl_acquisition import (
    build_bfcl_preflight_report,
    validate_bfcl_sampling_frame,
)
from kvopt.workload.phase5_dataset_processing import file_sha256


def _endpoint_models(base_url: str | None) -> list[str] | None:
    if not base_url:
        return None
    url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(url)
    api_key = os.getenv("REMOTE_OPENAI_API_KEY")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            value = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return [str(row["id"]) for row in value.get("data", []) if "id" in row]


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bfcl-root", type=Path, required=True)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--qualification-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("output already exists; preflight records are immutable")

    revision = subprocess.run(
        ["git", "-C", str(args.bfcl_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    frame = json.loads(args.frame.read_text(encoding="utf-8"))
    source_path = args.bfcl_root / frame["source"]["source_file"]
    validation = validate_bfcl_sampling_frame(
        frame_path=args.frame,
        source_path=source_path,
        observed_revision=revision,
    )
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    native = next(system for system in protocol["systems"] if system["id"] == "NATIVE")
    base_url = os.getenv("REMOTE_OPENAI_BASE_URL")
    report = build_bfcl_preflight_report(
        source_validation=validation,
        protocol_sha256=file_sha256(args.protocol),
        qualification_contract_sha256=file_sha256(args.qualification_contract),
        expected_model=native["model"],
        expected_model_revision=native["model_revision"],
        endpoint_models=_endpoint_models(base_url),
        serpapi_key_present=bool(os.getenv("SERPAPI_API_KEY")),
        model_endpoint_configured=bool(base_url),
    )
    _write(args.output / "source-validation.json", validation)
    _write(args.output / "preflight.json", report)
    _write(
        args.output / "sha256-manifest.json",
        {
            "schema_version": "phase5.dataset_sha256_manifest.v1",
            "files": [
                {
                    "path": name,
                    "sha256": file_sha256(args.output / name),
                }
                for name in ("preflight.json", "source-validation.json")
            ],
        },
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
