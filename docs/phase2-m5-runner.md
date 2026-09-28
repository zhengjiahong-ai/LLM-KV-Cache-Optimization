# Phase 2 M5 Runner: First Delivery

This is the reusable experimental entry point for Phase 2. It records logical
workload inputs separately from backend observations. The included backend is
an **explicitly synthetic infrastructure smoke**; its timings, blocks, prefix
identities, and forced release are not vLLM measurements or research results.

## Run the smoke

Install the project in editable mode, then run:

```bash
python -m pip install -e .
python -m benchmarks.run_phase2 \
  --config configs/phase2/smoke-config.json \
  --output-root artifacts/phase2
```

On a source checkout without installation, set `PYTHONPATH=src` first. The
runner prints the run directory and exits nonzero for a failed execution.

Each run writes `run.json` (config, provenance, status, availability),
`trace.json` (validated logical trace), `replay.jsonl` (requests actually
submitted), and `events.jsonl` (append-only raw backend observations). A failed
run keeps these partial files plus `stderr.log`. `event_index` orders records
within one run; timestamps carry an explicit clock domain and must not be
compared across domains without backend evidence. The runner stops each
pressure stage at the first observed forced-release decision or its configured
safety ceiling. It records `pressure_ceiling_reached` when no event appeared.

`trace.json` contains planned prompt construction, arrival offsets, turn and
tool-gap inputs, and pressure stages. It never contains observed block IDs,
native prefix IDs, or actual timestamps. Pressure prompts receive a seeded
unique suffix so they do not accidentally reuse the target prefix. Changing
policy or runtime mode in the config does not change the logical replay.

## Real backend boundary

`backend_factory` names a `module:callable` accepting `(config, event_sink)`.
It returns an object with `execute(PlannedRequest)` and `close()` methods.
The backend owns actual timing, scheduling, tokenization, generation, cache
settings, and pressure request execution. It must use approved runtime hooks:

- pass `event_sink` to `build_runtime(..., experiment_event_sink=...)` or
  `build_runtime_from_config(...)` for existing lifecycle events;
- pass `ExperimentForcedReleaseObserver(event_sink)` to
  `RetentionRuntimeIntegration` for complete decision-time candidates and
  selected pressure releases;
- emit any additional fact only when the backend directly observes it, with
  its real clock domain and source.

An optional `HardwareObservationProvider.describe()` can identify supported
hardware observations. Without a provider, the run remains valid and reports
hardware counters as unavailable. No generic GPU counter is fabricated.

## Current observation boundary

The approved event contracts currently expose request arrival/admission,
preemption conversion, turn finish, follow-up transitions, tool gaps,
prefix-to-block snapshots, block eviction conversion, and forced-release
decisions. The latter includes protected candidates, the original native free
queue, ordinary expiry, and selected pressure releases. Real vLLM APC hit/miss,
first-token timing, generated token counts, retention TTL provenance outside
the forced-release snapshot, and native cleanup completion still require
explicit backend observation interfaces. M1 must approve any new vLLM-facing
interface; these fields remain unavailable rather than inferred.

The committed smoke artifact under `docs/experiments/phase2-m5-smoke/` shows
the serialization path only. Formal Phase 2 experiments need a deployment
backend, pinned model/tokenizer revisions, and an approved protocol.
