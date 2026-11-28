#!/usr/bin/env python3
"""Rematerialize all accepted SWE prompts with the frozen 1.5B tokenizer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvopt.workload.phase5_dataset_processing import file_sha256
from kvopt.workload.phase5_swe_rematerialization import (
    materialize_accepted_swe_inventory,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-inventory", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, action="append", required=True)
    parser.add_argument("--tokenizer-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--qualification-contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer_root.resolve(), local_files_only=True
    )
    inventory = json.loads(args.candidate_inventory.read_text(encoding="utf-8"))
    summary = materialize_accepted_swe_inventory(
        candidate_inventory=inventory,
        evidence_roots=args.evidence_root,
        output_root=args.output,
        tokenizer=tokenizer,
        tokenizer_root=args.tokenizer_root,
        model_name="Qwen/Qwen2.5-Coder-1.5B-Instruct",
        model_revision="d18ecad881a290f0c792f1c2b5dbee1820d4a424",
        tokenizer_revision="d18ecad881a290f0c792f1c2b5dbee1820d4a424",
        protocol_sha256=file_sha256(args.protocol),
        qualification_contract_sha256=file_sha256(args.qualification_contract),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
