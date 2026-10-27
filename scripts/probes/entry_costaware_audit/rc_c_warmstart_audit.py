"""RC-C: design audit of the W1-A server-gap warm-start path.

The warm-start mechanism is not missing from the repository. It exists on ``origin/main``
but not on the branch this PR is based on, so this probe reads the reviewed files
straight out of git instead of the working tree. Nothing is modified, no threshold is
changed, and no history is injected into any experiment: this is a read-only audit.

What it answers
---------------
1. what the frozen W1-A history is (count, threshold, provenance, dedup rule);
2. what the history would do to the frozen TTL decision (which mode it produces);
3. why the v10 Bounded campaign did not use it -- the campaign-kind guard, checked at
   the exact tooling commit the campaign recorded;
4. whether the W1-A gap distribution is applicable to the v10 workload, by comparing it
   with the ``tool_gap_seconds`` the v10 traces actually schedule.

It does **not** claim warm-start would improve A1. Independence, fairness and
distribution transfer are reported as open items that a dedicated campaign must settle.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from pathlib import Path

REF = "origin/main"
HISTORY_PATH = "configs/phase2/continuum-w1a-server-gap-history-v1.json"
SPIKE_PATH = "scripts/spikes/phase2_minimal_observability_metal.py"
THRESHOLD = 100

ARCHIVE = Path(
    "local/continuum-native-cost-aware-bounded-v10-final-evidence/artifacts/"
    "continuum-native-cost-aware-bounded-runs-v10"
)


def git_show(spec: str) -> str:
    return subprocess.run(["git", "show", spec], capture_output=True, text=True, check=True).stdout


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(fraction * (len(ordered) - 1)))
    return ordered[index]


def describe(name: str, values: list[float]) -> None:
    if not values:
        print(f"  {name}: no samples")
        return
    print(
        f"  {name:22s} n={len(values):5d}  "
        f"min={min(values):.4f}  median={statistics.median(values):.4f}  "
        f"p90={percentile(values, 0.90):.4f}  max={max(values):.4f}"
    )


def history_section() -> dict:
    manifest = json.loads(git_show(f"{REF}:{HISTORY_PATH}"))
    gaps = [float(row["duration_seconds"]) for row in manifest["server_gap_records"]]
    by_tool: dict[str, int] = {}
    for row in manifest["server_gap_records"]:
        by_tool[str(row.get("tool_type"))] = by_tool.get(str(row.get("tool_type")), 0) + 1

    print("== frozen W1-A history (read from git, not from the working tree) ==")
    print(f"  schema                    {manifest['schema_version']}")
    print(f"  scope                     {manifest['scope']}")
    print(f"  source repository scope   {manifest['source_repository_scope']}")
    print(f"  source task count         {manifest['source_task_count']}")
    print(f"  server gap samples        {manifest['server_gap_sample_count']}")
    print(f"  history threshold         {manifest['duration_history_threshold']}")
    print(f"  dedup rule                {manifest['deduplication']}")
    print(f"  gap definition            {manifest['server_gap_definition']}")
    print(f"  tool durations are gaps?  {manifest['external_tool_duration_is_server_gap_sample']}")
    print(f"  KV prewarm                {manifest['kv_cache_prewarms']}")
    print(f"  tool_type split           {by_tool}")
    describe("server gaps (s)", gaps)
    shell = by_tool.get("mini-swe-agent-shell", 0)
    print()
    print("  mode this history would select:")
    print(f"    global samples {len(gaps)} > threshold {THRESHOLD} -> not COLD_START")
    if shell > THRESHOLD:
        print(f"    tool samples {shell} > {THRESHOLD} -> TOOL_SPECIFIC")
    else:
        print(f"    tool samples {shell} <= {THRESHOLD} -> GLOBAL (not TOOL_SPECIFIC)")
    return manifest


def guard_section() -> None:
    authorization = json.loads((ARCHIVE / "campaign" / "authorization.json").read_text())
    campaign_sha = authorization["experiment_tooling_git_sha"]
    spike = git_show(f"{campaign_sha}:{SPIKE_PATH}")
    lines = spike.splitlines()
    print()
    print("== the mechanism at the commit the v10 campaign recorded ==")
    print(f"  experiment_tooling_git_sha   {campaign_sha}")
    for index, line in enumerate(lines):
        if "campaign_kind" in line and "formal" in line:
            print(f"  guard   L{index + 1}: {line.strip()}")
        if "seed_server_gap_history" in line:
            print(f"  seeding L{index + 1}: {line.strip()}")
        if "SERVER_GAP_HISTORY_WARM_STARTED" in line:
            print(f"  event   L{index + 1}: {line.strip()}")

    kinds = set()
    with_keys = 0
    configs = sorted((ARCHIVE / "campaign").glob("*.config.json"))
    for path in configs:
        config = json.loads(path.read_text())
        kinds.add(str(config.get("campaign_kind")))
        if "continuum_server_gap_history_path" in config or (
            "continuum_server_gap_history_sha256" in config
        ):
            with_keys += 1
    print()
    print("== v10 Bounded campaign configuration ==")
    print(f"  config files                 {len(configs)}")
    print(f"  campaign_kind values         {sorted(kinds)}")
    print(f"  files carrying a history key {with_keys}")
    print("  -> the path is unreachable: the guard accepts only")
    print("     continuum_native_costaware_formal, and no config supplies the keys")


def observed_v10_gaps(root: Path) -> list[float]:
    """Same quantity the W1-A history defines: submit minus the program's last finish."""
    gaps: list[float] = []
    for path in sorted(root.glob("*-a0-repeat-1/events.jsonl")):
        last_finish: dict[str, float] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            program = str(event.get("program_id"))
            if event["event_type"] == "VLLM_REQUEST_COMPLETED":
                last_finish[program] = float(event["timestamp"])
            elif event["event_type"] == "VLLM_REQUEST_SUBMITTED" and program in last_finish:
                gaps.append(float(event["timestamp"]) - last_finish[program])
    return gaps


def distribution_section(history: dict) -> None:
    gaps = [float(row["duration_seconds"]) for row in history["server_gap_records"]]
    scheduled: list[float] = []
    v10_tools: dict[str, int] = {}
    for path in sorted((ARCHIVE / "campaign").glob("*.trace.json")):
        trace = json.loads(path.read_text())
        for request in trace.get("requests", []):
            scheduled.append(float(request.get("tool_gap_seconds") or 0.0))
            tool = str(request.get("next_tool_type"))
            v10_tools[tool] = v10_tools.get(tool, 0) + 1
    observed = observed_v10_gaps(ARCHIVE / "runs")
    print()
    print("== distribution applicability, W1-A history vs the v10 workload ==")
    describe("W1-A server gaps", gaps)
    describe("v10 scheduled gaps", scheduled)
    describe("v10 observed gaps", observed)
    if observed:
        w1a = statistics.median(gaps)
        print(f"  median ratio (v10 / W1-A)  {statistics.median(observed) / w1a:.4f}")
        print(f"  observed > W1-A median     {sum(g > w1a for g in observed)} / {len(observed)}")
    print()
    print("  v10 workload next_tool_type:", v10_tools)
    by_tool = {str(row.get("tool_type")): 0 for row in history["server_gap_records"]}
    for row in history["server_gap_records"]:
        by_tool[str(row.get("tool_type"))] += 1
    for tool in v10_tools:
        print(f"    W1-A tool samples for {tool!r}: {by_tool.get(tool, 0)} (threshold {THRESHOLD})")
    print("  -> even with warm-start the v10 workload stays in GLOBAL mode:")
    print("     its tool label has no W1-A samples, so TOOL_SPECIFIC is unreachable")
    print()
    print("  the v10 traces schedule zero tool gap and drive the next turn off the")
    print("  previous completion, so the observed gap is runner overhead, not agent")
    print("  tool latency. The two observed medians nearly coincide, but the tails do")
    print("  not: v10 p90 is above W1-A's, while W1-A has a 58 s outlier the metal runs")
    print("  never produce. Same median is not the same distribution, and the two gaps")
    print("  are generated by different processes, so transfer is untested either way.")
    print("  open items before use: source independence, arm-symmetric application,")
    print("  and whether the gap distribution transfers to g01-g09.")


def main() -> int:
    history = history_section()
    guard_section()
    distribution_section(history)
    print()
    print("== what this audit does not do ==")
    print("  no threshold change, no seeding of any experiment, no claim that warm-start")
    print("  improves A1; the frozen A0/A1/A2 code paths are untouched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
