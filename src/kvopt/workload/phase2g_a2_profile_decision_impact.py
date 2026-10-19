"""Audit whether repaired profile points can affect frozen Gate 2 decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from kvopt.continuum.prefill_profile import load_prefill_reload_provider
from kvopt.continuum.ttl import compute_default_ttl_seconds

HISTORY_THRESHOLD = 100
DEFAULT_TTL_TOKEN_COUNT = 256


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_decision_impact(
    *, manifest_path: Path, legacy_profile: Path, extended_profile: Path, smoke_root: Path
) -> dict[str, object]:
    manifest_path = manifest_path.resolve()
    root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    request_counts: dict[str, int] = {}
    for scenario in manifest["scenarios"]:
        trace = json.loads((root / str(scenario["trace"])).read_text(encoding="utf-8"))
        request_counts[str(scenario["scenario_id"])] = len(trace["requests"])
    maximum_request_count = max(request_counts.values())
    if maximum_request_count > HISTORY_THRESHOLD:
        raise ValueError("a frozen scenario can exceed the cold-start history threshold")

    legacy = load_prefill_reload_provider(legacy_profile)
    extended = load_prefill_reload_provider(extended_profile)
    legacy_256, _ = legacy.estimate(DEFAULT_TTL_TOKEN_COUNT)
    extended_256, _ = extended.estimate(DEFAULT_TTL_TOKEN_COUNT)
    if legacy_256 != extended_256:
        raise ValueError("extended profile changed the representative 256-token point")

    observed_events = 0
    maximum_observed_history_samples = 0
    for path in sorted(smoke_root.resolve().glob("*/events.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("event_type") != "TTL_HISTORY_INPUT_OBSERVED":
                continue
            observed_events += 1
            payload = event["payload"]
            maximum_observed_history_samples = max(
                maximum_observed_history_samples,
                int(payload["eta_history_sample_count"]),
                int(payload["queue_delay_history_sample_count"]),
            )
    if observed_events == 0:
        raise ValueError("Native smoke contains no TTL history observations")
    if maximum_observed_history_samples > HISTORY_THRESHOLD:
        raise ValueError("Native smoke exceeded the cold-start history threshold")

    default_ttl = compute_default_ttl_seconds(legacy_256)
    return {
        "schema_version": "phase2g.a2_profile_decision_impact_audit.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "manifest_sha256": _sha(manifest_path),
        "legacy_profile_sha256": _sha(legacy_profile),
        "extended_profile_sha256": _sha(extended_profile),
        "duration_history_threshold": HISTORY_THRESHOLD,
        "scenario_count": len(request_counts),
        "maximum_requests_in_any_scenario": maximum_request_count,
        "all_scenarios_bounded_below_or_at_threshold": True,
        "native_smoke_ttl_history_observation_count": observed_events,
        "native_smoke_maximum_observed_history_sample_count": (
            maximum_observed_history_samples
        ),
        "representative_default_ttl_token_count": DEFAULT_TTL_TOKEN_COUNT,
        "legacy_256_seconds": legacy_256,
        "extended_256_seconds": extended_256,
        "representative_point_exactly_preserved": True,
        "default_ttl_seconds": default_ttl,
        "decision_impact": "NO_POLICY_INPUT_CHANGE_UNDER_COLD_START",
        "reason": (
            "Every frozen scenario is bounded below the duration-history threshold; "
            "the observed Native smoke history counts are also below the threshold. "
            "COLD_START uses the default TTL derived from the exactly preserved "
            "256-token point, so 528/544 estimates are provider compatibility inputs "
            "and do not alter A0 Entry Release or A2 reuse-weight inputs."
        ),
        "formal_outcomes_inspected": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--legacy-profile", type=Path, required=True)
    parser.add_argument("--extended-profile", type=Path, required=True)
    parser.add_argument("--smoke-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = audit_decision_impact(
        manifest_path=args.manifest,
        legacy_profile=args.legacy_profile,
        extended_profile=args.extended_profile,
        smoke_root=args.smoke_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote A2 profile decision-impact audit: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
