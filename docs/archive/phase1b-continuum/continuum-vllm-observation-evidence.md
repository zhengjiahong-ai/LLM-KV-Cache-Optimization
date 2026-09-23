# Continuum vLLM GPU Observation Evidence

## Scope and authority

This document is the evidence contract and eventual result record for the
Phase 1B Continuum vLLM observation spike.

Authority remains, in order:

1. `docs/baseline-freeze.md`
2. `docs/phase1b-continuum-implementation-decisions.md`
3. `docs/experiment-plan.md`
4. `docs/architecture.md`
5. `docs/continuum-vllm-mapping.md`

The higher-priority documents freeze the following real-backend requirement:

```text
vLLM 0.27.1
+ real GPU inference
+ GPU Automatic Prefix Caching (APC)
```

They do not freeze NVIDIA, CUDA, Docker, a container image, or any GPU vendor.
The Docker image recorded in `docs/continuum-vllm-mapping.md` is the source
inspection environment used by that lower-priority spike, not a project-wide
runtime requirement.

Runtime constraints must originate from the authority above or from an
explicitly documented qualification requirement. A backend, vendor, container,
or development environment must not be promoted to a frozen project
requirement merely because one development path used it.

This document distinguishes four kinds of statements:

```text
FROZEN REQUIREMENT
    Required by the authority above.

SOURCE-VERIFIED DERIVATION
    Required or supported by the exact pinned runtime source.

PROJECT CONCRETIZATION
    A reviewed implementation choice used to make the frozen requirement
    executable. It is not attributed to the original freeze.

OPEN
    Not yet supported by sufficient source or runtime evidence.
```

The spike answers only the runtime questions needed to observe request/block
associations, choose a content-derived and namespace-aware `PrefixIdentity`,
and remove stale observation-session associations safely.

It does not implement TTL, retention, pressure release, scheduler reordering,
running-request preemption, Cost-Aware policy behavior, or performance
evaluation. Observation metadata remains advisory and cannot affect inference
correctness.

## Runtime requirement and candidate profile

### Frozen requirement

Formal `RUNTIME-VERIFIED` evidence must come from a runtime that demonstrates
the following frozen properties:

```yaml
vllm_release: 0.27.1
inference_device: real GPU
automatic_prefix_caching: true
```

PR 3 qualification additionally requires:

```yaml
expected_native_control_plane_reachable:
  - Scheduler
  - KVCacheManager
  - BlockPool
selected_observation_profile_uses_paged_kv: true
```

These requirements derive from the frozen native BlockPool eviction path,
native-cleanup ownership, and required real APC reuse/eviction validation.
They are qualification requirements for observing that behavior, not newly
claimed quotations from the three-item real-backend freeze.

Fake backends, source inspection, CPU-only inference, and simulator results may
test observation mechanics but cannot satisfy this formal runtime requirement.

### Apple Silicon Metal candidate

The first project runtime candidate is native Apple Silicon Metal. This is a
`PROJECT CONCRETIZATION`, not a newly inferred frozen requirement.

The following candidate identity is `SOURCE-VERIFIED` from the official
`vllm-project/vllm-metal` repository:

```yaml
source_repository: https://github.com/vllm-project/vllm-metal
vllm_metal_tag: v0.3.0.dev20260816085229
vllm_metal_commit: a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb
paired_vllm_distribution_expected: 0.27.1+cpu
paired_vllm_release_expected: 0.27.1
host_family: macOS Apple Silicon arm64
compute_backend: MLX / Metal
```

At that tag, the official installer pins the vLLM macOS arm64 wheel to
`0.27.1+cpu`. The local `+cpu` version segment describes the vLLM core wheel;
it does not by itself establish or refute Metal GPU execution. The Metal
plugin's runtime state must establish actual GPU use.

Source anchors for this candidate are the pinned tag's `install.sh`,
`pyproject.toml`, `vllm_metal/platform.py`, `docs/configuration.md`, and
`tests/test_paged_prefix_caching_e2e.py`. Source facts from another tag or from
the moving `main` branch cannot qualify this profile.

This candidate becomes an accepted formal evidence source only after the local
qualification run proves all of the following together:

```yaml
vllm_release_gate: PASS
vllm_metal_source_checkout_resolved: true
vllm_metal_source_head_matches_frozen_commit: true
vllm_metal_source_worktree_clean: true
imported_vllm_metal_module_inside_source_checkout: true
metal_platform_plugin_active: true
mlx_metal_available: true
mlx_configured_device: gpu
real_gpu_inference_completed: true
metal_paged_kv_enabled: true
automatic_prefix_caching_enabled: true
native_control_plane_hooks_reached: true
```

After the accepted qualification runs:

```yaml
candidate_pair_source_identity: SOURCE-VERIFIED
project_runtime_profile: RUNTIME-VERIFIED
metal_as_runtime_verified_source: RUNTIME-VERIFIED
qualification_status: PASS
```

If qualification shows that this pinned profile does not expose the required
vLLM 0.27.1 APC/BlockPool semantics, it must not produce formal evidence. The
failure is recorded honestly before another GPU environment is considered.

### Version and platform gates

The runner must record the complete installed vLLM distribution version and
compare its parsed PEP 440 release tuple with `(0, 27, 1)`. It must not use
prefix string matching. Thus `0.27.1+cpu` is acceptable for the release gate,
while `0.27.10` is not.

The vLLM-Metal distribution version is recorded verbatim but is not its source
identity. The formal source profile requires the resolved local checkout to be
at commit `a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb`, to have a clean Git working
tree, and to contain the resolved path of the imported `vllm_metal` module.
Path containment is checked using resolved paths, not string prefixes.

The pinned Metal platform deliberately may report a PyTorch-compatible
`device_type` or `device_name` of `cpu`. Neither a literal
`device_type == metal` check nor that compatibility field alone proves GPU
execution. Qualification must record the loaded Metal platform plugin, MLX
Metal availability, configured/default MLX device, and successful inference.

## Observation topology

Formal PR 3 observation requires:

```text
VLLM_ENABLE_V1_MULTIPROCESSING=0
```

This is a `SOURCE-VERIFIED DERIVATION` for the temporary monkeypatch topology,
not a GPU-vendor requirement. It must be set before Python imports vLLM, and
the runner must verify it before installing hooks or creating `LLM`. This keeps
the temporary `Scheduler` and `BlockPool` hooks in the same Python process as
`EngineCore`.

The exact upstream vLLM 0.27.1 source anchors are `vllm/envs.py`,
`vllm/v1/engine/llm_engine.py`, and `vllm/v1/engine/core_client.py`:
`VLLM_ENABLE_V1_MULTIPROCESSING=0` selects `InprocClient`, whereas the enabled
path selects the multiprocessing client.

It does not modify the Scheduler, BlockPool, or APC algorithms, but it does
change the EngineCore execution topology. Runtime conclusions are therefore
scoped to this in-process observation profile; they do not claim equivalence
for IPC, scheduling timing, or initialization behavior under the default
multiprocessing topology.

Observer OFF and ON runs must use the same topology. Only observer state may
change between the two sides of a comparison.

## Evidence levels and scenario outcomes

Document conclusions use only this `EvidenceLevel` vocabulary:

```text
PENDING
SOURCE-VERIFIED
RUNTIME-VERIFIED
RUNTIME-UNAVAILABLE
OPEN
BLOCKED
```

Scenario execution uses a separate `ScenarioOutcome` vocabulary:

```text
OBSERVED
NOT_OBSERVED
NOT_TESTED
```

The two fields are recorded independently. An unexecuted scenario is normally
`NOT_TESTED` with evidence level `PENDING`; it is not automatically
`RUNTIME-UNAVAILABLE`. That level requires evidence that the accepted runtime
or read-only observation surface cannot expose the fact. `OPEN` denotes an
intentionally undecided fact on which no current behavior may depend.

Runtime values continue to use only the five frozen `InputSource` values:

```text
NATIVE | OBSERVED | EXTERNAL | APPROXIMATED | UNAVAILABLE
```

`InputSource` is not an `EvidenceLevel`.

## Read-only observation contract

The observer may copy native state into immutable or JSON-compatible project
values. It must not:

- mutate requests, scheduler state, queue order, blocks, hashes, reference
  counts, or APC metadata;
- allocate, free, evict, reinsert, reorder, or schedule native objects;
- change native arguments, call order, return objects, or exception identity;
- retain native vLLM objects after a callback returns;
- infer `program_id` from `request_id`, hashes, tokens, or prompt text; or
- manufacture cache pressure by modifying the free queue.

For ordinary success and failure paths, a wrapped native function is called
exactly once. Observer failures must not replace native behavior. Hooks must be
temporary, removable, and restored after both success and failure.

Observer OFF/ON runs use identical deterministic workload inputs. They compare
output token IDs, completion status, and other externally visible deterministic
results; exact timing equality is not required. Internal native transitions are
recorded by the ON run. An OFF run with no hooks cannot itself prove equality of
internal admission or eviction sequences, and this document does not claim it
can.

`native_hash_hex` denotes an exact byte-preserving encoding of an available
native `KVCacheBlock.block_hash`. It must not be described as a bare content
hash or have presumed namespace bytes removed. Within the approved scoped
profile below, it is the canonical identity material for a reusable complete
block boundary. This approval does not claim cross-process or restart-persistent
stability.

## Required runtime record

Every accepted run records at least:

```yaml
run_id: REQUIRED
check_timestamp_utc: REQUIRED
task3_commit_sha: REQUIRED_CLEAN_COMMIT
host_operating_system: REQUIRED
host_version: REQUIRED
host_architecture: arm64
apple_chip: REQUIRED
python_version: REQUIRED

vllm_distribution_version_raw: REQUIRED
vllm_release_version: 0.27.1
vllm_metal_distribution_version_raw: REQUIRED
vllm_metal_source_checkout_realpath: REQUIRED
vllm_metal_source_commit: a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb
vllm_metal_source_worktree_clean: true
vllm_metal_imported_module_realpath: REQUIRED_INSIDE_SOURCE_CHECKOUT
pytorch_version: REQUIRED
mlx_version: REQUIRED
mlx_lm_version_or_revision: REQUIRED

platform_plugin_class: REQUIRED
platform_plugin_identity: REQUIRED
platform_device_type_raw: REQUIRED
mlx_metal_available: true
mlx_configured_device: gpu
mlx_default_device_raw: REQUIRED

model: REQUIRED
model_revision: REQUIRED_IMMUTABLE_INPUT
tokenizer: REQUIRED
tokenizer_revision: REQUIRED_IMMUTABLE_INPUT
block_size: REQUIRED
kv_cache_capacity_and_configuration: REQUIRED
automatic_prefix_caching: true
metal_paged_kv_enabled: true

vllm_enable_v1_multiprocessing: false
engine_core_observation_topology: in_process
observer_mode: off_or_on
scenario: REQUIRED
command: REQUIRED_REPRODUCIBLE_INVOCATION
```

The model and tokenizer revisions must be supplied to the launcher and used by
the real `LLM` construction. Discovering or recording a floating revision only
after execution is insufficient.

All history normalization or SHA-rewriting rebases must happen before the
formal evidence run. Once evidence records `task3_commit_sha`, that history
must not be rebased, reset, or force-pushed. If it is rewritten, the formal
matrix must be rerun and this provenance updated.

## Evidence sequencing

Commit 3 implements the native Metal runner, temporary hooks, scenarios, and
focused tests. A formal GPU evidence run is not a prerequisite for committing
that implementation; formal qualification and scenario evidence belong to
Commit 4. An earlier development smoke test may expose integration problems,
but it cannot populate the result table or create `RUNTIME-VERIFIED` claims.

This separation prevents an implementation commit from claiming the evidence
that the following evidence commit is responsible for collecting.

## Scenario matrix

There are exactly six workload scenarios:

| Scenario | Required observation | Requirement |
| --- | --- | --- |
| `environment_smoke` | Exact runtime identity, real GPU inference, paged KV, APC, and one completed request | mandatory |
| `request_lifecycle_cleanup` | Live, pre-cleanup, and post-cleanup request/block visibility | mandatory |
| `same_prefix_cross_request_reuse` | Different requests reuse one controlled prefix | mandatory |
| `namespace_isolation` | Vary one available namespace dimension while other inputs remain fixed | mandatory attempt |
| `block_eviction_and_reassignment` | Native cached eviction, metadata cleanup, and physical reuse when observed | cached eviction mandatory; reassignment best-effort |
| `partial_prefix` | Aligned and unaligned shared prefixes at the configured block size | mandatory attempt |

Observer OFF/ON is a comparison mode, not a seventh scenario. It is required
for `environment_smoke`, `same_prefix_cross_request_reuse`, and
`block_eviction_and_reassignment`.

Both sides of every OFF/ON comparison use
`VLLM_ENABLE_V1_MULTIPROCESSING=0`; only the observer mode changes.

Real native cached eviction and its metadata cleanup are mandatory evidence.
Physical block reassignment is best-effort: failure to observe reassignment
must not trigger unbounded pressure tuning or a fabricated generation/epoch
mechanism. Record its scenario outcome and evidence level honestly.

Missing reassignment or partial-prefix evidence records both fields
independently under these rules:

```text
scenario not executed
    -> NOT_TESTED + PENDING

scenario executed but the event was not observed
    -> NOT_OBSERVED + OPEN

runtime/read-only surface shown unable to expose the fact
    -> NOT_OBSERVED + RUNTIME-UNAVAILABLE
```

`NOT_OBSERVED + PENDING` is not an allowed final pairing: after execution, the
result must either remain explicitly `OPEN` or have evidence for
`RUNTIME-UNAVAILABLE`.

## Raw evidence layout

Raw output is written under the ignored path:

```text
results/continuum-observation/<run-id>/
├── environment.json
├── commands.txt
├── observations.jsonl
├── summary.json
└── stderr.log
```

Raw evidence, environment artifacts, model weights, model caches, private
prompts, credentials, and large logs are not committed. Only concise
conclusions and the final identity decision enter Git.

The launcher owns the run directory, `commands.txt`, and `stderr.log` so the
recorded command includes the complete environment-prefixed invocation and the
actual process stderr. The runner creates only `environment.json`,
`observations.jsonl`, and `summary.json`. Any observer exception is isolated
from native inference but increments `observer_error_count` and makes the
summary status `INVALID`, never `SUCCESS`.

## Formal run synthesis

The formal matrix was executed against the clean Commit 3 implementation
`2e4fd4ca7b93ea050592e5ca66e1e9929cabf73c` and the clean Metal source checkout
`a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb`. All accepted runs used the same
text-only model and tokenizer revisions, CPython 3.12.14 arm64, vLLM release
`0.27.1` (raw distribution version `0.27.1+cpu`), vLLM-Metal `0.3.0`, MLX
`0.32.0`, block size 16, APC enabled, paged KV enabled, and the in-process
observation topology (`VLLM_ENABLE_V1_MULTIPROCESSING=0`).

The common runtime identity was:

```yaml
host_operating_system: Darwin
host_version: 15.6
host_architecture: arm64
apple_chip: Apple M4
python_version: 3.12.14
vllm_metal_source_commit: a8b7e75c412aedcefe26ac3ab98d2a76e3e166fb
vllm_metal_source_worktree_clean: true
model: Qwen/Qwen2.5-0.5B-Instruct
model_revision: 7ae557604adf67be50417f59c2c2f167def9a775
tokenizer: Qwen/Qwen2.5-0.5B-Instruct
tokenizer_revision: 7ae557604adf67be50417f59c2c2f167def9a775
```

The formal raw run directories referenced by this synthesis are ignored and
remain outside Git:

```yaml
environment_smoke:
  - metal-smoke-off-2e4fd4c
  - metal-smoke-on-2e4fd4c
request_lifecycle_cleanup:
  - metal-lifecycle-on-2e4fd4c
same_prefix_cross_request_reuse:
  - metal-reuse-off-2e4fd4c
  - metal-reuse-on-2e4fd4c
namespace_isolation:
  - metal-namespace-on-2e4fd4c
block_eviction_and_reassignment:
  - metal-eviction-off-2e4fd4c
  - metal-eviction-on-2e4fd4c
  - metal-eviction2-off-2e4fd4c
  - metal-eviction2-on-2e4fd4c
partial_prefix:
  - metal-partial-prefix-on-2e4fd4c
```

The shared model inputs were:

```yaml
model: Qwen/Qwen2.5-0.5B-Instruct
model_revision: 7ae557604adf67be50417f59c2c2f167def9a775
tokenizer: Qwen/Qwen2.5-0.5B-Instruct
tokenizer_revision: 7ae557604adf67be50417f59c2c2f167def9a775
```

The first eviction attempt is retained as an executed but insufficient
attempt: with `32` requests and `256` prompt tokens it produced no cached
eviction (`NOT_OBSERVED` + `OPEN`). The approved bounded second attempt used
`128` requests, `512` prompt tokens, `max_tokens=8`, and
`gpu_memory_utilization=0.30`. Its paired native observations showed cached
eviction and metadata cleanup: 160 allocation calls contained eviction and
27,816 pre-call non-null cached hashes became null on the returned allocated
blocks. Physical block reassignment was not explicitly observed.

The reuse run showed 12 complete prefix blocks (16 through 192 tokens) with
the same native hashes and block IDs on the second request, while only one new
partial block was allocated. The namespace run held the token prefix fixed and
changed only `cache_salt`; all non-null native hashes differed between the two
requests. The partial-prefix run showed sharing of the complete blocks for
both aligned and unaligned pairs, while the final partial block had no hash.

## Result table

The following table is populated only by a formal run that first passes the
candidate qualification. It must not be filled from fake objects, source
inspection, or third-party runtime reports alone.

| Question | Scenario outcome | EvidenceLevel | Result / reason |
| --- | --- | --- | --- |
| Exact vLLM 0.27.1 real-GPU/APC profile accepted | `OBSERVED` | `RUNTIME-VERIFIED` | Apple Silicon Metal profile completed real inference with MLX GPU, paged KV, APC, and the expected native control-plane hooks |
| Live request-to-block association visible | `OBSERVED` | `RUNTIME-VERIFIED` | Lifecycle ON observations linked the live request to native blocks before cleanup |
| Association disappears at cleanup | `OBSERVED` | `RUNTIME-VERIFIED` | Post-cleanup snapshots no longer contained the request association or its blocks |
| Same-prefix cross-request APC hit/reuse demonstrated | `OBSERVED` | `RUNTIME-VERIFIED` | Second request reused the 12 complete native prefix blocks and allocated only its final partial block |
| Native hash encoding stable and usable | `OBSERVED` | `RUNTIME-VERIFIED` | Exact native `block_hash` bytes were preserved as lowercase hex and matched across the reuse and partial-prefix observations; approved canonical identity material within the scoped profile, not a profile-independent identity |
| `cache_salt` namespace isolation behavior known | `OBSERVED` | `RUNTIME-VERIFIED` | `cache_salt` alone changed all non-null native hashes for the fixed text prefix; no LoRA, multimodal, or prompt-embedding namespace was exercised |
| Native cached eviction and metadata cleanup visible | `OBSERVED` | `RUNTIME-VERIFIED` | Eviction attempt 2 (`128 x 512`) observed cached eviction and the associated hash/metadata cleanup; attempt 1 remains recorded as insufficient |
| Physical block reassignment visible | `NOT_OBSERVED` | `OPEN` | No explicit reassignment event was present in the approved read-only observations; no generation mechanism is inferred |
| Partial-prefix behavior known | `NOT_OBSERVED` | `OPEN` | Complete 16- and 32-token blocks were shared for aligned and unaligned pairs; final partial-block suffix semantics were not established |
| Observer OFF/ON externally visible deterministic results equivalent | `OBSERVED` | `RUNTIME-VERIFIED` | Smoke, reuse, and eviction OFF/ON pairs completed successfully with matching externally visible output token IDs and completion status |

Partial-prefix sub-conclusions are recorded separately:

| Partial-prefix fact | Scenario outcome | EvidenceLevel | Result / reason |
| --- | --- | --- | --- |
| Complete aligned/shared blocks | `OBSERVED` | `RUNTIME-VERIFIED` | The first two complete blocks (16 and 32 tokens) were shared for both aligned and unaligned pairs |
| Final partial-block suffix semantics | `NOT_OBSERVED` | `OPEN` | The final partial block had no native hash; suffix usefulness is not inferred |

## PrefixIdentity construction decision

The formal run approves a narrowly scoped `PrefixIdentity` construction. The
exact native hash is retained without stripping its encoded group material.
`cache_salt` was shown to affect that native material. Only ordinary token-ID
text input with single-cache-group Metal behavior was exercised; LoRA,
multimodal, and prompt-embedding namespaces remain outside the supported
evidence profile.

| Candidate field | Scenario outcome | EvidenceLevel | Include in v1 identity | Reason |
| --- | --- | --- | --- | --- |
| exact native hash encoding | `OBSERVED` | `RUNTIME-VERIFIED` | yes | Exact byte-preserving lowercase-hex encoding of the complete native `KVCacheBlock.block_hash`; the source hash chain and same-prefix reuse evidence establish it for the approved scoped profile |
| cache group representation | `OBSERVED` | `RUNTIME-VERIFIED` | no | Runtime observed `cache_group_id=0`; source evidence shows the group ID is retained in native hash material. Independent multi-group behavior was not exercised |
| cache salt behavior | `OBSERVED` | `RUNTIME-VERIFIED` | no | Changing only `cache_salt` changed every non-null native hash for the fixed prefix; no separate field is approved |
| LoRA namespace | `NOT_TESTED` | `PENDING` | no | Outside the approved text-only profile |
| multimodal namespace | `NOT_TESTED` | `PENDING` | no | Outside the approved text-only profile |
| prompt-embedding namespace | `NOT_TESTED` | `PENDING` | no | Outside the approved ordinary token-ID text profile |

Machine-readable decision:

```yaml
decision_status: APPROVED
schema_version: continuum.prefix.native_hash.v1
supported_runtime_profile:
  host: macOS Apple Silicon arm64
  backend: MLX / Metal
  vllm_release: 0.27.1
  text_only: true
  prefix_caching_hash_algo: sha256
  process_scope: one_live_EngineCore_process
  engine_core_observation_topology: in_process
  vllm_enable_v1_multiprocessing: false
  cache_groups: exactly_one
  cache_group_id: 0
  block_size: 16
  cache_salt: represented_in_native_hash_material
  lora: excluded_not_tested
  multimodal: excluded_not_tested
  prompt_embeds: excluded_not_tested
  model: Qwen/Qwen2.5-0.5B-Instruct
  model_revision: 7ae557604adf67be50417f59c2c2f167def9a775
  tokenizer: Qwen/Qwen2.5-0.5B-Instruct
  tokenizer_revision: 7ae557604adf67be50417f59c2c2f167def9a775
  cross_process_identity: unsupported
  restart_persistent_identity: unsupported
candidate_identity_material:
  - native_hash_hex
included_fields:
  - native_hash_hex
canonical_encoding:
  native_hash_hex:
    source: KVCacheBlock.block_hash
    native_type: BlockHashWithGroupId
    encoding: lowercase_hex_of_exact_native_bytes
    preserve_group_id_suffix: true
boundary_guard:
  native_hash_hex_required: true
  hash_num_tokens_required: true
  complete_block_only: true
  hash_num_tokens_must_be_positive: true
  hash_num_tokens_mod_block_size_must_equal: 0
namespace_rules:
  cache_group: represented_in_native_hash_material
  cache_salt: represented_in_native_hash_chain
  lora: outside_supported_profile
  multimodal: outside_supported_profile
  prompt_embeds: outside_supported_profile
identity_rules:
  - preserve native_hash_hex exactly
  - never strip or reconstruct native hash material
  - hash_num_tokens gates construction but is not an identity field
  - never use request_id
  - never use block_id as logical identity
  - never reconstruct from prompt text
  - never use repr(), str(), or Python hash()
eviction_cleanup_supported: true
reassignment_tracking_supported: false
process_lifetime_limitation: >-
  vLLM 0.27.1 may initialize NONE_HASH from os.urandom(32) when
  PYTHONHASHSEED is not fixed; this decision therefore covers cross-request
  reuse within one live EngineCore process only, not cross-process or restart
  persistence.
```

Commit 4 may set `decision_status: APPROVED` only when all of the following
hold:

- `included_fields` is non-empty;
- every included field was exercised, has scenario outcome `OBSERVED`, has
  evidence level `RUNTIME-VERIFIED`, and is explicitly included by the final
  decision;
- the included representation is sufficient to identify the observed reusable
  prefix within the explicitly supported runtime profile; and
- every correctness-relevant namespace dimension known from source or runtime
  evidence for the supported profile is verified and represented,
  is already encoded by verified native identity material, or causes the
  decision to be narrowed to the verified profile or marked `BLOCKED`.

A field whose `ScenarioOutcome` is `NOT_TESTED` or `NOT_OBSERVED`, or whose
`EvidenceLevel` is `PENDING`, `OPEN`, or `RUNTIME-UNAVAILABLE`, must not be
silently encoded.

The canonical representation must never use `request_id`, `block_id` alone,
Python `hash()`, unstable `repr()`/`str()`, or reconstructed prompt text.

If an unverified namespace dimension may be necessary for correctness, scope
the decision to the verified runtime profile or mark it `BLOCKED`. If physical
reassignment was not observed, the implementation may apply only
evidence-supported stale cleanup and must leave reassignment tracking open.

## Open and blocked questions

The formal run resolved the Metal real-GPU/APC qualification, live association
and cleanup boundary, same-prefix reuse, `cache_salt` isolation, cached
eviction cleanup, and the scoped native-hash `PrefixIdentity` decision. The
following remain explicitly open or unsupported:

- LoRA, multimodal, and prompt-embedding namespace behavior
  (`NOT_TESTED` + `PENDING`), which are outside the approved profile;
- physical block reassignment (`NOT_OBSERVED` + `OPEN`);
- final partial-block suffix semantics (`NOT_OBSERVED` + `OPEN`); and
- cross-process or restart-persistent identity, which is unsupported by this
  profile; and
- any behavior outside the recorded macOS Apple Silicon MLX/Metal,
  ordinary token-ID text-only, single-cache-group profile.

No unresolved item may be hidden by an inferred identity field or synthetic
lifecycle mechanism.

## Acceptance criteria

PR 3 evidence is acceptable when:

- a local runtime demonstrates vLLM release 0.27.1, real GPU inference, paged
  KV cache, and GPU APC, with complete backend/plugin/hardware provenance;
- the controlled same-prefix scenario demonstrates a real APC cache hit/reuse,
  rather than merely confirming that an enable flag was set;
- all six scenarios have an honest outcome and evidence level;
- smoke, reuse, and eviction have observer OFF/ON comparisons using the same
  in-process topology and compare only evidence available in both modes;
- a real native cached eviction and its metadata cleanup are observed without
  observer-driven queue mutation;
- every JSON/JSONL output parses and each required scenario/mode has one
  summary;
- raw evidence remains ignored and contains no credentials or model data;
- the identity decision is either evidence-backed `APPROVED` or precisely
  `BLOCKED`; and
- reassignment remains best-effort and no unsupported generation mechanism is
  invented merely to complete the document.
