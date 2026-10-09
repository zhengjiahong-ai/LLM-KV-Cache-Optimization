"""Materialize the authorized H1 Level-A formal campaign without running it."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from .phase2_h1_compiler import compile_h1_scenario


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain an object")
    return value


def materialize_h1_formal_campaign(
    *,
    scenario_manifest_path: Path,
    scenario_seal_path: Path,
    authorization_path: Path,
    base_config_path: Path,
    output: Path,
    execution_code_commit: str,
) -> Path:
    """Compile all 42 sealed draws after validating the separate authorization."""
    if re.fullmatch(r"[0-9a-f]{40}", execution_code_commit) is None:
        raise ValueError("execution_code_commit must be a full Git SHA")
    manifest = _object(scenario_manifest_path)
    seal = _object(scenario_seal_path)
    authorization = _object(authorization_path)
    base = _object(base_config_path)
    if manifest.get("schema_version") != "phase2a.h1_sealed_scenario_manifest.v2":
        raise ValueError("formal H1 requires the v2 sealed scenario manifest")
    if seal.get("scenario_manifest_sha256") != _sha(scenario_manifest_path):
        raise ValueError("scenario seal does not bind the supplied manifest")
    if authorization.get("formal_h1_outcome_execution_authorized") is not True:
        raise ValueError("formal H1 execution is not authorized")
    if authorization.get("challenger", {}).get("runtime_policy_switch_authorized") is not False:
        raise ValueError("challenger runtime policy switch must remain disabled")
    if authorization.get("scenario_manifest_sha256") != _sha(scenario_manifest_path):
        raise ValueError("authorization does not bind the scenario manifest")
    if authorization.get("scenario_seal_sha256") != _sha(scenario_seal_path):
        raise ValueError("authorization does not bind the scenario seal")
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 42:
        raise ValueError("formal H1 requires exactly 42 sealed scenarios")
    output.mkdir(parents=True, exist_ok=False)
    compiled = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise TypeError("sealed scenario must be an object")
        scenario_id = scenario.get("scenario_id")
        family_id = scenario.get("family_id")
        if not isinstance(scenario_id, str) or not isinstance(family_id, str):
            raise TypeError("sealed scenario identity is invalid")
        config, trace, evidence = compile_h1_scenario(
            scenario,
            base,
            formal_h1_outcome_execution_authorized=True,
        )
        trace_text = json.dumps(trace.to_dict(), indent=2, sort_keys=True) + "\n"
        config_text = json.dumps(config, indent=2, sort_keys=True) + "\n"
        evidence_text = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        trace_path = output / f"{scenario_id}.trace.json"
        config_path = output / f"{scenario_id}.config.json"
        evidence_path = output / f"{scenario_id}.evidence-contract.json"
        trace_path.write_text(trace_text, encoding="utf-8")
        config_path.write_text(config_text, encoding="utf-8")
        evidence_path.write_text(evidence_text, encoding="utf-8")
        compiled.append(
            {
                "scenario_id": scenario_id,
                "family_id": family_id,
                "structural_sha256": scenario["structural_sha256"],
                "config": config_path.name,
                "config_sha256": _sha(config_path),
                "trace_sha256": _sha(trace_path),
                "evidence_contract_sha256": _sha(evidence_path),
            }
        )
    family_counts = Counter(item["family_id"] for item in compiled)
    if family_counts != Counter({family: 7 for family in ("F1", "F2", "F3", "F4", "F5", "F6")}):
        raise ValueError("compiled formal campaign must contain seven draws per family")
    campaign = {
        "schema_version": "phase2a.formal_campaign.v2",
        "campaign_id": "phase2a-h1-independent-holdout-v2",
        "campaign_kind": "formal",
        "evidence_tier": "LEVEL_A_PROXY_FIRST",
        "primary_metric": "planned_return_weighted_prefill_proxy",
        "verdict_ceiling": "PROXY_CANDIDATE",
        "formal_h1_outcome_execution_authorized": True,
        "challenger_runtime_policy_switch_authorized": False,
        "authorization_record": str(authorization_path.resolve()),
        "authorization_record_sha256": _sha(authorization_path),
        "scenario_manifest_sha256": _sha(scenario_manifest_path),
        "scenario_seal_sha256": _sha(scenario_seal_path),
        "execution_code_commit": execution_code_commit,
        "requires_clean_execution_worktree": True,
        "seeds": [101, 211, 307],
        "predeclared_repetitions_per_scenario": 3,
        "planned_run_count": 126,
        "family_scenario_counts": dict(sorted(family_counts.items())),
        "scenarios": compiled,
    }
    path = output / "campaign.json"
    path.write_text(json.dumps(campaign, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-manifest", type=Path, required=True)
    parser.add_argument("--scenario-seal", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--base-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execution-code-commit", required=True)
    arguments = parser.parse_args(argv)
    path = materialize_h1_formal_campaign(
        scenario_manifest_path=arguments.scenario_manifest,
        scenario_seal_path=arguments.scenario_seal,
        authorization_path=arguments.authorization,
        base_config_path=arguments.base_config,
        output=arguments.output,
        execution_code_commit=arguments.execution_code_commit,
    )
    print(f"wrote formal H1 Level-A campaign: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
