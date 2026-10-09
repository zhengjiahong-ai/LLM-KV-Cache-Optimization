"""Materialize authorized formal H2 M1 inputs with frozen configurations."""

import argparse
import hashlib
import json
from pathlib import Path

from .phase2_h2_calibration import _trace


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materialize_formal_m1(authorization_path: Path, output: Path) -> Path:
    authorization = json.loads(authorization_path.read_text())
    if authorization.get("schema_version") != "phase2a.h2_measurement_authorization.v1":
        raise ValueError("unsupported H2 authorization")
    if authorization.get("formal_h2_measurement_authorized") is not True:
        raise ValueError("formal H2 measurement is not authorized")
    root = Path(__file__).resolve().parents[3]
    submission_path = root / "configs/phase2/h2-final-authorization-submission.json"
    if _sha(submission_path) != authorization["submission_sha256"]:
        raise ValueError("reviewed submission hash mismatch")
    bindings = {
        "numeric_audit_sha256": "docs/experiments/phase2a-m6-h2/isolated-calibration-numeric-audit.json",
        "independent_verifier_sha256": "scripts/audit_h2_bootstrap.py",
        "final_freeze_record_sha256": "configs/phase2/h2-final-freeze-record.json",
        "formal_freeze_spec_sha256": "configs/phase2/h2-formal-freeze-spec.json",
    }
    for key, name in bindings.items():
        if _sha(root / name) != authorization["bindings"][key]:
            raise ValueError(f"authorization binding mismatch: {key}")
    protocol = authorization["protocol"]
    if protocol["warmup_repeats"] != 2 or protocol["measured_repeats"] != 9:
        raise ValueError("formal protocol must retain 2 warmups and 9 measurements")
    configurations = authorization["m1_execution_configurations"]
    expected_grid = [16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192,
                     12288, 16384, 20480, 24576, 26624, 28672, 30720]
    if [row["prefix_tokens"] for row in configurations] != expected_grid:
        raise ValueError("formal M1 grid mismatch")
    for row in configurations:
        encoded = json.dumps(row["config"], sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()
        if hashlib.sha256(encoded).hexdigest() != row["config_sha256"]:
            raise ValueError("frozen execution configuration hash mismatch")
    output.mkdir(parents=True, exist_ok=False)
    points = []
    for row in configurations:
        tokens = row["prefix_tokens"]
        config = row["config"]
        config_name = f"r{tokens}.config.json"
        trace = _trace(tokens).to_dict()
        trace_text = json.dumps(trace, indent=2, sort_keys=True) + "\n"
        (output / config_name).write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        (output / config["trace"]).write_text(trace_text)
        runs = [
            {"run_id": f"m1-r{tokens}-{role}-{index}", "role": role}
            for role, count in (("warmup", 2), ("measured", 9))
            for index in range(1, count + 1)
        ]
        points.append({"prefix_tokens": tokens, "config": config_name,
                       "runtime_config_sha256": row["config_sha256"],
                       "trace_sha256": hashlib.sha256(trace_text.encode()).hexdigest(),
                       "runs": runs})
    manifest = {
        "schema_version": "phase2a.h2_formal_m1_campaign.v1",
        "campaign_id": "phase2a-h2-formal-m1-v1",
        "authorization_sha256": _sha(authorization_path),
        "formal_measurement": True,
        "formal_verdict_authorized": False,
        "b1_authorized": False,
        "planned_run_count": 187,
        "warmup_repeats_per_point": 2,
        "measured_repeats_per_point": 9,
        "delta_M1_seconds": authorization["delta_M1_seconds"],
        "points": points,
    }
    path = output / "campaign.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(f"wrote formal H2 M1 campaign: {materialize_formal_m1(args.authorization, args.output)}")
