"""Materialize the non-formal H2 native intervention validation campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .phase2_h2_mechanism import (
    _canonical_sha,
    _load_authorization,
    _mechanism_config,
    _trace,
)

_PROBES = (
    {
        "probe_id": "h2v-no-eviction",
        "prefix_tokens": 512,
        "position": None,
        "evicted_blocks": 0,
        "expected_cached_prefix_tokens": 512,
    },
    {
        "probe_id": "h2v-trailing-j4",
        "prefix_tokens": 512,
        "position": "trailing",
        "evicted_blocks": 4,
        "expected_cached_prefix_tokens": 448,
    },
    {
        "probe_id": "h2v-leading-j4",
        "prefix_tokens": 512,
        "position": "leading",
        "evicted_blocks": 4,
        "expected_cached_prefix_tokens": 0,
    },
    {
        "probe_id": "h2v-r1024-full-evict",
        "prefix_tokens": 1024,
        "position": "trailing",
        "evicted_blocks": 64,
        "expected_cached_prefix_tokens": 0,
    },
)


def materialize_h2_intervention_validation(
    authorization_path: Path,
    output: Path,
) -> Path:
    authorization_path = authorization_path.resolve()
    authorization = _load_authorization(authorization_path)
    output.mkdir(parents=True, exist_ok=False)
    probes: list[dict[str, object]] = []
    for frozen in _PROBES:
        probe_id = frozen["probe_id"]
        assert isinstance(probe_id, str)
        prefix_tokens = int(frozen["prefix_tokens"])
        trace_name = f"{probe_id}.trace.json"
        config_name = f"{probe_id}.config.json"
        trace = _trace(probe_id, prefix_tokens).to_dict()
        config = _mechanism_config(
            authorization,
            probe_id=probe_id,
            prefix_tokens=prefix_tokens,
            trace_name=trace_name,
            position=frozen["position"],  # type: ignore[arg-type]
            count=int(frozen["evicted_blocks"]),
            campaign_kind="h2_intervention_validation",
        )
        config["h2_measurement"] = {
            **config["h2_measurement"],  # type: ignore[misc]
            "formal_measurement": False,
            "validation_only": True,
        }
        trace_text = json.dumps(trace, indent=2, sort_keys=True) + "\n"
        config_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
        (output / trace_name).write_text(trace_text, encoding="utf-8")
        (output / config_name).write_text(config_text, encoding="utf-8")
        probes.append(
            {
                **frozen,
                "config": config_name,
                "runtime_config_sha256": _canonical_sha(config),
                "config_file_sha256": hashlib.sha256(
                    config_text.encode()
                ).hexdigest(),
                "trace_sha256": hashlib.sha256(trace_text.encode()).hexdigest(),
                "run_id": probe_id,
            }
        )
    campaign = {
        "schema_version": "phase2a.h2_intervention_validation_campaign.v1",
        "campaign_id": "phase2a-h2-intervention-validation-v1",
        "authorization_sha256": hashlib.sha256(
            authorization_path.read_bytes()
        ).hexdigest(),
        "formal_measurement": False,
        "formal_verdict": False,
        "b1_authorized": False,
        "planned_run_count": 4,
        "probes": probes,
    }
    path = output / "campaign.json"
    path.write_text(
        json.dumps(campaign, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(
        "wrote H2 intervention validation campaign: "
        f"{materialize_h2_intervention_validation(args.authorization, args.output)}"
    )
