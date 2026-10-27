"""E1 / E6 feasibility on the M6 agent trajectories, not on H1.

Why this script exists
----------------------
The first version of this probe used H1 Level-A. H1 is a synthetic pressure harness:
one fixed content per program, ``max_new_tokens = 1``, two or three turns per
program, and a first request that can never hit. It has 120 entry decisions and no
prefix growth at all, so it cannot answer a question about real agent reuse.

M6 owns the real trajectories: SWE-bench Verified tasks executed by Mini-SWE-Agent
against a pinned Qwen coder model, captured as acquisition sidecars that carry the
submitted token IDs and both clocks for every model call. That is the data this
probe targets.

Two modes
---------
``committed``  the raw sidecars are not in git, so this mode reads the aggregates
               M6 committed on the W1-C branch and reports what they already settle.
``sidecars``   when a run root is available (``--runs-root`` or ``$W1_RUNS_ROOT``),
               the same probe computes E1 and E6 per call from
               ``<run>/<instance>/acquisition-sidecar.json``.

Metric definitions are taken from the W1-C report so the numbers stay comparable:
``adjacent_exact_lcp_tokens`` is the longest common prefix of consecutive submitted
token-ID lists, ``adjacent_reuse_ratio`` divides that by the previous prompt length,
and ``context_growth_tokens`` is last minus first prompt length for one task.

E1 has three non-interchangeable variants, and this script names the one it uses
every time it prints a number:

``E1a hit rate``
    fraction of prior same-chain requests whose native cached tokens were > 0. This
    is the only variant that answers "did reuse actually happen", and it needs
    native observations. Neither dataset available here provides it, so it is not
    computed anywhere in this file.
``E1b reuse ratio``
    adjacent exact-token LCP divided by the previous prompt length. Near 1.0 whenever
    context accumulates, which makes it close to a tautology for agent trajectories.
``E1c reuse magnitude``
    the adjacent LCP in tokens. Approximately the previous prompt length, therefore
    largely collinear with the block count the score already consumes.

The earlier H1-based probe reported E1a; this one reports E1b and E1c. The change of
operationalisation is deliberate and declared rather than silent.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

W1C_REF = "origin/feature/continuum-w1c-expanded-workload-pilot"
W1C_DOC = "docs/continuum-w1c-feasibility-pilot.md"
W1A_REF = "origin/feature/continuum-w1a-trajectory-acquisition"

SIDECAR = "acquisition-sidecar.json"


def git_show(ref: str, path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{ref}:{path}"], capture_output=True, text=True, check=True
    ).stdout


def numbers(text: str) -> list[float]:
    """Numeric cells of a markdown row, tolerating thousands separators."""
    values = []
    for match in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        values.append(float(match.replace(",", "")))
    return values


def committed_aggregates() -> dict[str, dict[str, float]]:
    """Parse the committed W1-C tables instead of transcribing them by hand."""
    text = git_show(W1C_REF, W1C_DOC)
    result: dict[str, dict[str, float]] = {}
    for line in text.splitlines():
        if not line.startswith("| S50 |") and not line.startswith("| S100 |"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        condition = cells[0]
        values = numbers(" ".join(cells[1:]))
        if len(values) == 4:
            result.setdefault(condition, {}).update(
                runs=values[0],
                successful_calls=values[1],
                failed_calls=values[2],
                tool_calls=values[3],
            )
        elif len(values) == 3:
            result.setdefault(condition, {}).update(
                natural_completion=values[0],
                step_censored=values[1],
                context_limit=values[2],
            )
        elif len(values) == 5:
            result.setdefault(condition, {}).update(
                median_prompt_tokens=values[0],
                max_prompt_tokens=values[1],
                median_context_growth=values[2],
                median_adjacent_lcp=values[3],
                median_adjacent_reuse_ratio=values[4],
            )
    return result


def describe(name: str, values: list[float], width: int = 30) -> None:
    if not values:
        print(f"  {name:{width}s} no samples")
        return
    ordered = sorted(values)
    print(
        f"  {name:{width}s} n={len(ordered):5d}  min={ordered[0]:.4f}  "
        f"p50={statistics.median(ordered):.4f}  p90={ordered[int(0.9 * (len(ordered) - 1))]:.4f}  "
        f"max={ordered[-1]:.4f}"
    )


def committed_mode() -> int:
    aggregates = committed_aggregates()
    print("== M6 committed W1-C aggregates (read from git, not retyped) ==")
    print(f"  source branch   {W1C_REF}")
    print(f"  source document {W1C_DOC}")
    print()
    for condition in sorted(aggregates):
        row = aggregates[condition]
        print(f"  {condition}")
        print(f"    runs                       {row.get('runs')}")
        print(f"    successful model calls     {row.get('successful_calls')}")
        print(f"    failed model calls         {row.get('failed_calls')}")
        print(f"    tool calls                 {row.get('tool_calls')}")
        print(f"    median prompt tokens       {row.get('median_prompt_tokens')}")
        print(f"    max prompt tokens          {row.get('max_prompt_tokens')}")
        print(f"    median context growth      {row.get('median_context_growth')}")
        print(f"    median adjacent LCP        {row.get('median_adjacent_lcp')}")
        print(f"    median adjacent reuse      {row.get('median_adjacent_reuse_ratio')}")
        print()

    s50 = aggregates.get("S50", {})
    s100 = aggregates.get("S100", {})
    total_calls = sum(row.get("successful_calls", 0) for row in aggregates.values())
    print("== what these aggregates already settle ==")
    print(f"  real model calls available                {int(total_calls)}")
    print(
        f"  runs                                      "
        f"{int(sum(row.get('runs', 0) for row in aggregates.values()))}"
    )
    if s50 and s100:
        ratio_delta = s100["median_adjacent_reuse_ratio"] - s50["median_adjacent_reuse_ratio"]
        calls_s50 = s50["successful_calls"] / s50["runs"]
        calls_s100 = s100["successful_calls"] / s100["runs"]
        per_call_s50 = s50["median_context_growth"] / calls_s50
        per_call_s100 = s100["median_context_growth"] / calls_s100
        print()
        print("  E1b (adjacent exact-token reuse ratio), not E1a:")
        print(
            f"    S50 {s50['median_adjacent_reuse_ratio']:.4f}   "
            f"S100 {s100['median_adjacent_reuse_ratio']:.4f}   "
            f"delta {ratio_delta:+.4f}"
        )
        print("    both are close to 1.0, so the ratio is nearly saturated: as a")
        print("    ranking feature it has little room to separate candidates. On agent")
        print("    trajectories this is close to tautological, since the next prompt is")
        print("    the previous prompt plus tool output.")
        print()
        print("  E1c (adjacent LCP tokens) tracks the prompt length:")
        print(
            f"    median adjacent LCP  S50 {s50['median_adjacent_lcp']:.0f}  "
            f"S100 {s100['median_adjacent_lcp']:.0f} tokens"
        )
        print(
            f"    median prompt        S50 {s50['median_prompt_tokens']:.0f}  "
            f"S100 {s100['median_prompt_tokens']:.0f} tokens"
        )
        print("    the LCP is roughly the whole previous prompt, so E1c is largely")
        print("    collinear with N, which the score already consumes.")
        print()
        print("  E6, context growth:")
        print(
            f"    median per-task growth  S50 {s50['median_context_growth']:.0f}  "
            f"S100 {s100['median_context_growth']:.0f} tokens"
        )
        print(f"    calls per task          S50 {calls_s50:.0f}  S100 {calls_s100:.0f}")
        print(
            f"    implied growth per call S50 {per_call_s50:.0f}  "
            f"S100 {per_call_s100:.0f} tokens  (ratio "
            f"{per_call_s100 / per_call_s50:.2f}x)"
        )
        print("    the doubled budget roughly doubles growth, while growth per call is")
        print("    nearly unchanged. So E6 carries information only if per-task growth")
        print("    rates differ, which the aggregates cannot show.")
    print()
    print("== what these aggregates cannot settle ==")
    print("  E1a hit rate is not measurable here at all: it needs native cached-token")
    print("  observations, and neither H1 nor W1-C provides them.")
    print("  per-call E1b / E1c / E6 coverage and distributions, and whether they differ")
    print("  between the programs that are candidates at the same moment.")
    print("  that needs the sidecars, not the summary table.")
    return 0


def lcp(left: list[int], right: list[int]) -> int:
    count = 0
    for first, second in zip(left, right, strict=False):
        if first != second:
            break
        count += 1
    return count


def find_run_roots(explicit: str | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("W1_RUNS_ROOT")
    if env:
        candidates.append(Path(env))
    for guess in (
        "local/w1c-runs",
        "local/w1a-runs",
        "local/continuum-w1c-pilot",
        "runs",
    ):
        candidates.append(Path(guess))
    return [path for path in candidates if path.is_dir()]


def sidecar_calls(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    calls = []
    for call in payload.get("model_calls") or []:
        if call.get("status") != "SUCCESS":
            continue
        tokens = call.get("submitted_token_ids")
        if not isinstance(tokens, list) or not tokens:
            continue
        calls.append(
            {
                "turn": int(call.get("turn_index") or 0),
                "submit": float(call.get("model_submit_monotonic_seconds") or 0.0),
                "complete": float(call.get("model_completion_monotonic_seconds") or 0.0),
                "tokens": tokens,
            }
        )
    calls.sort(key=lambda call: call["submit"])
    return calls


def sidecar_mode(roots: list[Path]) -> int:
    print("== M6 sidecar mode ==")
    for root in roots:
        print(f"  scanning {root}")
    sidecars = []
    for root in roots:
        sidecars.extend(sorted(root.glob(f"**/{SIDECAR}")))
    print(f"  sidecars found                            {len(sidecars)}")
    if not sidecars:
        print("  nothing to analyse; pass --runs-root <dir> or set W1_RUNS_ROOT")
        return 0

    per_program: dict[str, list[dict]] = {}
    for path in sidecars:
        calls = sidecar_calls(path)
        if len(calls) >= 2:
            per_program[str(path.parent)] = calls

    e1: list[float] = []
    e1_magnitude: list[float] = []
    e6_per_call: list[float] = []
    e6_per_second: list[float] = []
    coverage = Counter()
    programs = 0
    for calls in per_program.values():
        programs += 1
        for index in range(1, len(calls)):
            # Everything used here is strictly before the current call.
            prior_pairs = [(calls[i - 1], calls[i]) for i in range(1, index)]
            prior_growth = [
                len(calls[i]["tokens"]) - len(calls[i - 1]["tokens"]) for i in range(1, index)
            ]
            coverage[f"prior_pairs={min(len(prior_pairs), 2)}"] += 1
            if len(prior_pairs) >= 1:
                ratios = [
                    lcp(p["tokens"], c["tokens"]) / max(1, len(p["tokens"])) for p, c in prior_pairs
                ]
                e1.append(sum(ratios) / len(ratios))
                magnitudes = [lcp(p["tokens"], c["tokens"]) for p, c in prior_pairs]
                e1_magnitude.append(sum(magnitudes) / len(magnitudes))
            if len(prior_growth) >= 1:
                e6_per_call.append(sum(prior_growth) / len(prior_growth))
                elapsed = [calls[i]["submit"] - calls[i - 1]["submit"] for i in range(1, index)]
                pairs = [
                    growth / dt for growth, dt in zip(prior_growth, elapsed, strict=True) if dt > 0
                ]
                if pairs:
                    e6_per_second.append(sum(pairs) / len(pairs))

    print(f"  programs with at least two calls         {programs}")
    print(f"  calls eligible for a prior-only estimate {sum(coverage.values())}")
    for key in sorted(coverage):
        print(f"    {key:22s} {coverage[key]}")
    print()
    describe("E1b prior adjacent reuse", e1)
    describe("E1c prior LCP tokens", e1_magnitude)
    describe("E6 prior growth per call", e6_per_call)
    describe("E6 prior growth per second", e6_per_second)
    print()

    program_means = []
    for calls in per_program.values():
        if len(calls) < 3:
            continue
        growth = [
            len(calls[i]["tokens"]) - len(calls[i - 1]["tokens"]) for i in range(1, len(calls))
        ]
        program_means.append(sum(growth) / len(growth))
    if len(program_means) >= 3:
        ordered = sorted(program_means)
        spread = ordered[int(0.9 * (len(ordered) - 1))] - ordered[int(0.1 * (len(ordered) - 1))]
        print("  cross-program spread of mean growth per call:")
        print(
            f"    min {ordered[0]:.1f}  median {statistics.median(ordered):.1f}  "
            f"max {ordered[-1]:.1f}  p10-p90 spread {spread:.1f} tokens"
        )
        print("    this is the quantity an Entry decision would rank on: if the spread")
        print("    is wide relative to the per-call noise, E6 is actionable.")
    print()
    print("  leakage checks applied here:")
    print("    - only calls with submit time before the current call are used")
    print("    - the current call's own token list is never read for its own feature")
    print("    - no cross-program and no cross-run pooling")
    return 0


def main(argv: list[str]) -> int:
    explicit = None
    if "--runs-root" in argv:
        explicit = argv[argv.index("--runs-root") + 1]
    roots = find_run_roots(explicit)
    print(f"script: {Path(__file__).name}")
    print()
    committed_mode()
    print()
    if roots:
        sidecar_mode(roots)
    else:
        print("== M6 sidecar mode ==")
        print("  no run root found. Pass --runs-root <dir> or set W1_RUNS_ROOT to the")
        print("  directory that holds <run>/<instance>/acquisition-sidecar.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
