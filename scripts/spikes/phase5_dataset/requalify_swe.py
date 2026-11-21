"""Requalify immutable Phase 5 SWE Sessions under the current protocol."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from kvopt.workload.phase5_dataset_processing import (
    build_collection_summary,
    file_sha256,
    qualify_existing_session,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--qualification-contract", type=Path, required=True)
    parser.add_argument("--terminal-adjudication", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError("output already exists; historical results are immutable")
    protocol_sha = file_sha256(args.protocol)
    contract_sha = file_sha256(args.qualification_contract)
    adjudication_sha = file_sha256(args.terminal_adjudication)
    adjudication = json.loads(args.terminal_adjudication.read_text(encoding="utf-8"))
    forced_exclusions = adjudication["forced_exclusions"]
    reports: list[dict[str, object]] = []
    manifest: list[dict[str, str]] = []
    for session in sorted((args.input / "sessions").iterdir()):
        if not session.is_dir():
            continue
        output_session = args.output / "sessions" / session.name
        output_session.mkdir(parents=True)
        for name in (
            "normalized-trace.json",
            "token-materialization.json",
            "tool-fixtures.json",
        ):
            shutil.copyfile(session / name, output_session / name)
        report = qualify_existing_session(
            session_directory=session,
            protocol_sha256=protocol_sha,
            qualification_contract_sha256=contract_sha,
            terminal_adjudication=forced_exclusions,
            terminal_adjudication_sha256=adjudication_sha,
        )
        qualification_path = output_session / "qualification.json"
        _write(qualification_path, report)
        reports.append(report)
        for path in sorted(output_session.iterdir()):
            manifest.append(
                {
                    "path": path.relative_to(args.output).as_posix(),
                    "sha256": file_sha256(path),
                }
            )
    summary = build_collection_summary(
        reports=reports,
        protocol_sha256=protocol_sha,
        qualification_contract_sha256=contract_sha,
    )
    _write(args.output / "collection-summary.json", summary)
    manifest.extend(
        [
            {
                "path": "collection-summary.json",
                "sha256": file_sha256(args.output / "collection-summary.json"),
            }
        ]
    )
    _write(
        args.output / "sha256-manifest.json",
        {
            "schema_version": "phase5.dataset_sha256_manifest.v1",
            "files": sorted(manifest, key=lambda row: row["path"]),
        },
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
