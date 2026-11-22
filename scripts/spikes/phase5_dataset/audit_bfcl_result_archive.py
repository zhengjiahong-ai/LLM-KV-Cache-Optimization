#!/usr/bin/env python3
"""Audit the two pinned public BFCL-Result Agentic JSON archives."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from kvopt.workload.phase5_bfcl_result_audit import (
    audit_result_file,
    build_archive_audit,
)
from kvopt.workload.phase5_dataset_processing import file_sha256

BASE_RELATIVE = Path(
    "2025-12-16/result/gpt-5.2-2025-12-11-FC/agentic"
)
FILES = (
    ("BFCL_v4_web_search_base_result.json", "SNIPPET", "c58f1cb0c19d5b6c8874dda45adaa2ae58570db4"),
    ("BFCL_v4_web_search_no_snippet_result.json", "NO_SNIPPET", "bd6bd4ae3b53442d86fd33776a1ded6b48f23de5"),
)


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-repository", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    commit = subprocess.check_output(
        ["git", "-C", str(args.result_repository), "rev-parse", "HEAD"], text=True
    ).strip()
    source_rows = _jsonl(args.source)
    frame = json.loads(args.frame.read_text())
    file_audits = [
        audit_result_file(
            path=args.result_repository / BASE_RELATIVE / name,
            mode=mode,
            source_rows=source_rows,
            frame_cases=frame["cases"],
            expected_blob_sha1=blob,
            observed_blob_sha1=subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(args.result_repository),
                    "hash-object",
                    str(BASE_RELATIVE / name),
                ],
                text=True,
            ).strip(),
        )
        for name, mode, blob in FILES
    ]
    report = build_archive_audit(
        repository_commit=commit,
        repository_url="https://github.com/HuanzhiMao/BFCL-Result",
        license_id="Apache-2.0",
        repository_license_sha256=file_sha256(args.result_repository / "LICENSE"),
        repository_readme_sha256=file_sha256(args.result_repository / "README.md"),
        file_audits=file_audits,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    report_path = args.output / "archive-audit.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    summary = {
        key: report[key]
        for key in (
            "schema_version",
            "repository_commit",
            "source_model",
            "frozen_frame_exact_id_coverage",
            "frozen_frame_exact_content_match",
            "total_record_count",
            "semantic_trace_complete_count",
            "replay_ready_count",
            "direct_reuse_status",
            "global_blockers",
            "archive_audit_sha256",
        )
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    manifest = {
        "archive_audit_sha256": file_sha256(report_path),
        "summary_sha256": file_sha256(args.output / "summary.json"),
        "frame_sha256": file_sha256(args.frame),
        "source_sha256": file_sha256(args.source),
        "repository_license_sha256": file_sha256(
            args.result_repository / "LICENSE"
        ),
        "repository_readme_sha256": file_sha256(
            args.result_repository / "README.md"
        ),
    }
    (args.output / "sha256-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
