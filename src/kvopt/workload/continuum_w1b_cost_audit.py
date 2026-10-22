"""Audit W1-B replay token counts against frozen PrefillReload support."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from kvopt.continuum.prefill_profile import load_prefill_reload_provider


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_cost_coverage(*, freeze_path: Path, profile_path: Path) -> dict[str, Any]:
    freeze = _load(freeze_path)
    if freeze.get("schema_version") != "continuum.w1b_native_smoke_freeze.v1":
        raise ValueError("unsupported W1-B smoke freeze")
    provider = load_prefill_reload_provider(profile_path)
    rows: list[dict[str, Any]] = []
    for group in freeze["groups"]:
        for session in group["sessions"]:
            counts = session["selected_token_counts"]
            request_ids = session["selected_request_ids"]
            for request_id, token_count in zip(request_ids[:-1], counts[:-1], strict=True):
                reusable_tokens = int(token_count) // 16 * 16
                try:
                    seconds, provenance = provider.estimate(reusable_tokens)
                except ValueError:
                    rows.append(
                        {
                            "group_id": group["group_id"],
                            "session_id": session["session_id"],
                            "request_id": request_id,
                            "observed_prompt_tokens": token_count,
                            "prefill_reload_query_tokens": reusable_tokens,
                            "status": "OUTSIDE_FROZEN_PROFILE",
                            "estimate_seconds": None,
                            "provenance": None,
                        }
                    )
                else:
                    rows.append(
                        {
                            "group_id": group["group_id"],
                            "session_id": session["session_id"],
                            "request_id": request_id,
                            "observed_prompt_tokens": token_count,
                            "prefill_reload_query_tokens": reusable_tokens,
                            "status": "SUPPORTED",
                            "estimate_seconds": seconds,
                            "provenance": {
                                "source": provenance.source.value,
                                "reason": provenance.reason,
                            },
                        }
                    )
    unsupported = [row for row in rows if row["status"] != "SUPPORTED"]
    affected_arms = {
        "A0": "TurnFinished requires PrefillReload to construct TTL input",
        "A1": "A1 entry-release cost consumes the same TTL PrefillReload input",
        "A2": "A2 keeps A0 entry release, which requires the same TTL input",
    }
    return {
        "schema_version": "continuum.w1b_prefill_reload_coverage_audit.v1",
        "freeze_sha256": _sha256(freeze_path),
        "profile_sha256": _sha256(profile_path),
        "query_count": len(rows),
        "supported_query_count": len(rows) - len(unsupported),
        "unsupported_query_count": len(unsupported),
        "minimum_query_tokens": min(row["prefill_reload_query_tokens"] for row in rows),
        "maximum_query_tokens": max(row["prefill_reload_query_tokens"] for row in rows),
        "queries": rows,
        "affected_arms": affected_arms,
        "existing_long_context_measurement_reuse": "NOT_JUSTIFIED",
        "reason": (
            "H2 isolated synchronized prefill timing is not the frozen Phase 1B "
            "MISS-HIT TTFT PrefillReload measurement contract"
        ),
        "execution_gate": (
            "BLOCKED_PREFILL_RELOAD_RANGE" if unsupported else "PASS"
        ),
        "formal_performance_campaign_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_cost_coverage(freeze_path=args.freeze, profile_path=args.profile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"W1-B cost coverage: {report['execution_gate']} "
        f"({report['supported_query_count']}/{report['query_count']} supported) "
        f"-> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
