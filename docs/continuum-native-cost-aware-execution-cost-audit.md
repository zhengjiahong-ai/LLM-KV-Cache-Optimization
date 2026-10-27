# Bounded Native Cost-Aware Evaluation Execution Cost Audit

Audit target: `c882d6be8616bf48eee581977a3b8d610ae3c76e`

Scope: static code inspection and analysis of existing W1-C evidence only. No
formal Profile point or Native campaign run was started, and no frozen protocol
field was changed.

## Verdict

The current `8–20 GPU hours` is a budget envelope, not a measured estimate for
the frozen 1.5B/RTX 4090D substrate. The bounded campaign materializer and
runner do not yet exist, so campaign timing, pressure-request counts, engine
initialization time, and request time are not measured.

One material avoidable risk is already identifiable: interpreting the interval
between two selected W1-C checkpoints as idle replay time would include the
execution of omitted Agent turns. Sleeping those intervals would add about
`6.01` billed GPU hours over 54 runs. That behavior is not implemented today
and must not be introduced implicitly.

The Profile implementation is concrete. It performs seven engine
initializations, seven Seed requests, 70 MISS requests, 70 HIT requests, and a
variable number of 512-token pressure requests. Pressure is already checked
after each individual request, so there is no fixed 32-request overrun to
remove.

## 1. Replay timing

### Implemented behavior

The bounded protocol freezes:

- cross-session stagger: 0.25 seconds;
- within-session timing: observed completion-to-next-submit gap when valid;
- maximum concurrent requests: two.

No bounded campaign materializer or runner currently consumes these fields.
They are design intent, not execution evidence. The existing generic Phase 2
runner executes trace actions serially. The existing backend sleeps only when
`backend_options.execute_planned_timing=true`; it sleeps until an absolute
offset from run start. Its asynchronous `submit()` path rejects that setting
because timing must then be owned by an external runner. Existing W1-B configs
set `execute_planned_timing=false` and therefore do not demonstrate the new
timing policy or two-request concurrency.

### Static wait calculation from accepted W1-C evidence

Each session selects six integer-quantile checkpoints. In 17 of 18 sessions,
the source has 100 successful calls and selects indexes
`[0, 19, 39, 59, 79, 99]`. Consequently, the timestamp difference from one
selected call's completion to the next selected call's submission includes the
model/tool work of calls that are not replayed.

If a future runner sleeps these selected-to-selected differences literally,
the estimated per-group waits are:

| Group | Wall wait per run, two sessions overlapped |
|---|---:|
| g01 | 762.479 s |
| g02 | 530.412 s |
| g03 | 339.951 s |
| g04 | 415.670 s |
| g05 | 274.139 s |
| g06 | 327.423 s |
| g07 | 354.916 s |
| g08 | 233.209 s |
| g09 | 369.166 s |

One nine-group sweep is about `1.002 h`; six pressure/arm sweeps are about
`6.012 h`. This is billed wall time with an idle GPU, not GPU work. The fixed
0.25-second session stagger contributes at most `13.5 s` over all 54 runs and
is immaterial.

For comparison, the completion-to-immediate-next-source-call gaps at the five
selected transition points sum to only about 23 seconds across all 18
sessions. This is not automatically a valid replacement: it compresses the
omitted trajectory interval and may alter TTL, deadline/q, overlap, and
retention state.

### Recommendation

Before final freeze, define a runner-level timing contract. Do not map raw
selected-to-selected timestamp differences directly to `sleep()`.

Preferred candidate for M1 review: a deterministic logical clock that retains
the frozen lifecycle/deadline timestamps while requests are physically replayed
without long idle wall-clock sleeps. It needs an explicit proof that native
cache state depends only on the frozen ordering, concurrency, capacity, and
pressure events, and that no wall-clock-dependent native behavior is being
claimed. A simpler scale/cap transform has lower implementation cost but
changes the A1 deadline/q input and therefore carries higher research risk.
Deleting all gaps is not acceptable.

## 2. PrefillReload work accounting

The implemented point runner initializes one engine, calls
`ensure_seeded(token_count)` once, then executes two Warmup pairs and eight
Measured pairs. Every pair performs pressure until the target's first Native
Hash is absent, one validated full MISS, and one validated HIT.

For all seven points, the exact non-pressure request counts are:

| Work | Requests | Full-prompt token input |
|---|---:|---:|
| Seed | 7 | 98,823 |
| Warmup MISS | 14 | 197,646 |
| Measured MISS | 56 | 790,584 |
| Warmup HIT | 14 | 197,646 submitted; mostly cached work |
| Measured HIT | 56 | 790,584 submitted; mostly cached work |
| Total | 147 | 2,075,283 submitted tokens |

The table counts the one-token suffix used by the runner. HIT submitted tokens
must not be equated with recomputed tokens.

Pressure requests are not fixed, but the capacity geometry implies roughly
`ceil(anchor/512)` requests per pair: approximately 1,930 requests and 988,160
pressure input tokens across 70 pairs. The fail-closed range is 70–4,480
pressure requests. Existing 3B/Metal observations (not transferable as timing
measurements) recorded 57 requests per 28,672-token pair and 64 per
32,256-token pair, supporting the conclusion that pressure is a major part of
the work.

Changing two Warmup pairs to one would produce 63 pairs. It removes seven MISS,
seven HIT, and seven pressure cycles: about 197,646 target request tokens plus
about 98,816 pressure tokens under the capacity estimate, or about 9.7% of
Profile input-token work. It does not remove any of the seven engine
initializations or Seed requests.

Recommendation: retain two Warmup pairs for the final-freeze candidate unless
target 1.5B/4090D evidence shows that the first and second warmups are stable.
Every point starts a fresh engine, so kernel, allocator, and cache startup
transients are credible. Reducing warmup now saves only about 10% of Profile
loops while weakening protection against a first-pair transient. This is a
protocol option, not an approved change.

## 3. Initialization and execution paths

### Profile

The CLI measures one token point per process. It constructs one backend/engine
for that point and closes it after measurement. Seven anchors therefore imply
seven model loads. Reusing one engine is not a behavior-preserving optimization
because the configured KV block capacity changes with the target length; the
vLLM pool cannot be resized after initialization.

### Native campaign

The 54-run bounded runner is `NOT_IMPLEMENTED`. Existing Phase 2 runners create
one backend per config invocation and close it, which would imply 54 model
loads, but that is only the likely inherited execution model, not established
bounded-runner behavior. There is no clean reset contract for BlockPool,
Retention state, hash identity, hooks, scheduler state, or RNG that would make
cross-run engine reuse safe. The backend explicitly requires a fresh process
after policy hooks are installed.

Thus the projected total is 61 engine initializations (7 Profile + 54
campaign), but initialization duration on the frozen 1.5B/4090D target is
`NOT_MEASURED`.

The 648 checkpoint requests are planned, not executed. Campaign pressure
request count is also `NOT_IMPLEMENTED` because numeric 24GB capacity and
shortage remain pending. Request execution, physical pressure, result writing,
and initialization durations are all `NOT_MEASURED` on the target substrate.

## 4. Cost model

The only defensible model before implementation and target measurement is:

`billed = setup + profile work + campaign work + initialization + replay idle + closeout`

and

`GPU work = profile GPU work + campaign GPU work + GPU portions of initialization`.

These quantities overlap if initialization is also included inside Profile or
campaign wall time; they must not be added twice.

| Stage | Confirmed workload | Time status | Billing implication |
|---|---|---|---|
| Environment preparation | install, model download, cache verification | NOT_MEASURED; planning allowance 0.5–2 h | Mostly idle but fully billed if done on the GPU instance |
| PrefillReload Profile | 70 pairs, 7 Seeds, about 1,930 pressure requests | NOT_MEASURED on 1.5B/4090D; planning allowance 1.5–5 h | Mostly real GPU work |
| Native campaign | 54 runs, 648 checkpoints, unknown pressure count | NOT_IMPLEMENTED/NOT_MEASURED; planning allowance 3–10 h | Mostly real GPU work plus any replay idle |
| Repeated initialization | projected 61 engine constructions | NOT_MEASURED; sensitivity: 30–120 s each = 0.51–2.03 h | Real load/setup work; already included if measured end-to-end |
| Replay waiting | fixed stagger <=13.5 s; literal selected-gap policy about 6.01 h | Policy NOT_IMPLEMENTED | GPU idle but billed |
| Closeout/evaluation | validation, archive, offline statistics | NOT_MEASURED; planning allowance 0.25–1 h | Can be moved off paid GPU; near-zero GPU work |

The planning allowances explain why `8–20 h` is plausible, but they are not
measurements. With a literal selected-gap sleep, the design can consume roughly
six additional billed hours without additional GPU work. Without that mistake,
the dominant irreducible uncertainty remains genuine long-context Prefill and
pressure execution, not Python orchestration.

Before authorization, record on the exact target instance: engine-ready
latency, per-request Native duration, pressure request count/duration, idle
sleep, evidence-write time, and end-to-end run duration as separate fields.
One pre-authorization feasibility execution may only be performed if separately
authorized by M1.

## 5. Optimization candidates

Ordered by expected value and research risk:

1. **Reject selected-to-selected literal sleep** — potential saving about 6.01
   billed hours; high value. Adopt only an M1-approved logical-time or timing
   transform contract because A1 uses time-derived inputs.
2. **Prepare outside the paid window** — prebuild the environment, retain the
   model/pip cache, materialize configs, and perform validation/archive analysis
   locally. Likely saves 0.5–3 billed hours depending on download/install and
   operator delay; no research impact.
3. **Keep per-request pressure early-stop** — already implemented. Removing or
   batching the identity check would save little and could over-evict, so no
   change is recommended.
4. **Warmup 2 to 1** — saves about 9.7% of Profile input work but has moderate
   measurement risk and no target stability evidence. Do not adopt before M1
   review.
5. **Cross-run engine reuse** — could remove part of 54 loads, but no safe reset
   contract exists and the policy hook requires fresh processes. High fidelity
   risk; not recommended for this freeze.
6. **Cross-anchor engine reuse** — incompatible with point-specific KV capacity;
   not recommended without redefining the Profile protocol.

## Final recommendation

Keep the Profile at 2+8 pairs for now. Before final freeze, block implementation
of literal selected-checkpoint sleeps and require an explicit timing/clock
contract. Implement duration telemetry before trusting the 8–20-hour budget.
The likely large cost is genuine long-context Prefill plus pressure, while the
only currently quantifiable avoidable cost is up to about six hours of
misinterpreted replay waiting.
