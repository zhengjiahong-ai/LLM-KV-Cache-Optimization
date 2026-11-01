"""Prepare or run the authorized Phase 2I A3 target CUDA Native preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from kvopt.workload.phase2i_a3_cuda_preflight import (
    _write_sha_manifest,
    materialize_preflight,
    run_preflight,
)

TIMEOUT_SECONDS = 1800
TERMINATION_GRACE_SECONDS = 60


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--authorization-record", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())


def _archive_execution(
    *,
    input_dir: Path,
    output_root: Path,
    authorization_record: Path,
    outcome: dict[str, object],
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "execution-envelope.json").write_text(
        json.dumps(outcome, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_sha_manifest(output_root)
    archive_path = output_root.parent / f"{output_root.name}-evidence.tar.gz"
    if archive_path.exists():
        raise FileExistsError(archive_path)
    with tarfile.open(archive_path, "x:gz") as archive:
        archive.add(input_dir, arcname=f"inputs/{input_dir.name}")
        archive.add(output_root, arcname=f"outputs/{output_root.name}")
        archive.add(authorization_record, arcname="authorization/m1-authorization.json")
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    print(f"EVIDENCE_ARCHIVE: {archive_path}")
    print(f"EVIDENCE_ARCHIVE_SHA256: {digest}")
    return archive_path


def _run_bounded(arguments: argparse.Namespace) -> int:
    parent_token = secrets.token_hex(32)
    command = (
        sys.executable,
        "-u",
        "-m",
        "scripts.spikes.run_phase2i_a3_cuda_preflight",
        "_run-once",
        "--parent-token",
        parent_token,
        "--input-dir",
        str(arguments.input_dir.resolve()),
        "--output-root",
        str(arguments.output_root.resolve()),
        "--authorization-record",
        str(arguments.authorization_record.resolve()),
        "--repository",
        str(arguments.repository.resolve()),
    )
    started = time.monotonic()
    environment = dict(os.environ)
    environment["PHASE2I_BOUNDED_PARENT_TOKEN"] = parent_token
    process = subprocess.Popen(command, env=environment)
    timed_out = False
    forced_kill = False
    try:
        return_code = process.wait(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.send_signal(signal.SIGINT)
        try:
            return_code = process.wait(timeout=TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            forced_kill = True
            process.kill()
            return_code = process.wait()
    elapsed = time.monotonic() - started
    outcome = {
        "schema_version": "phase2i.a3_bounded_execution_envelope.v1",
        "status": "TIMEOUT" if timed_out else ("COMPLETE" if return_code == 0 else "FAILED"),
        "return_code": return_code,
        "timeout_seconds": TIMEOUT_SECONDS,
        "termination_grace_seconds": TERMINATION_GRACE_SECONDS,
        "timed_out": timed_out,
        "forced_kill": forced_kill,
        "wall_elapsed_seconds": elapsed,
    }
    _archive_execution(
        input_dir=arguments.input_dir,
        output_root=arguments.output_root,
        authorization_record=arguments.authorization_record,
        outcome=outcome,
    )
    return return_code if return_code != 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--source-config", type=Path, required=True)
    prepare.add_argument("--source-trace", type=Path, required=True)
    prepare.add_argument("--profile", type=Path, required=True)
    prepare.add_argument("--predecessor-archive", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--repository", type=Path, default=Path.cwd())
    execute = subparsers.add_parser("run")
    _add_run_arguments(execute)
    execute_once = subparsers.add_parser("_run-once", help=argparse.SUPPRESS)
    _add_run_arguments(execute_once)
    execute_once.add_argument("--parent-token", required=True)
    arguments = parser.parse_args()
    if arguments.command == "prepare":
        result = materialize_preflight(
            source_config_path=arguments.source_config,
            source_trace_path=arguments.source_trace,
            profile_path=arguments.profile,
            predecessor_archive_path=arguments.predecessor_archive,
            output_dir=arguments.output_dir,
            repository=arguments.repository,
        )
        print(f"PREPARED: {arguments.output_dir}")
        print(f"git_sha: {result['git_sha']}")
        return 0
    if arguments.command == "run":
        return _run_bounded(arguments)
    if os.environ.get("PHASE2I_BOUNDED_PARENT_TOKEN") != arguments.parent_token:
        raise RuntimeError("internal execution requires the bounded parent wrapper")
    result = run_preflight(
        input_dir=arguments.input_dir,
        output_root=arguments.output_root,
        repository=arguments.repository,
        authorization_path=arguments.authorization_record,
    )
    print(f"{result['status']}: {arguments.output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
