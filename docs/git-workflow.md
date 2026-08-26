# Git Workflow

Repository: `zhengjiahong-ai/LLM-KV-Cache-Optimization`

## 1. Core Rules

`main` is the stable branch. All formal project work eventually merges into `main`.

Do **not** develop or commit directly on `main`.

Use this workflow:

```text
latest main
  ↓
create a task branch
  ↓
complete one clearly scoped task
  ↓
test
  ↓
push
  ↓
Pull Request
  ↓
review
  ↓
merge into main
```

Do not treat member branches as permanent personal folders for the entire project.

---

## 2. Current Team Responsibilities

| Member | Primary responsibility |
|---|---|
| Member 1 | Architecture / backend integration / overall coordination |
| Member 2 | Related Work / Motivation |
| Member 3 | Baseline reproduction |
| Member 4 | Optimization design & implementation |
| Member 5 | Dataset / Workload / Benchmark |
| Member 6 | Evaluation / Profiling / Results |
| Member 7 | Slides / Presentation |

Existing broad branches such as:

```text
feature/related-work
feature/baseline
feature/optimization
feature/workload
feature/evaluation
docs/presentation
```

may be used as current-stage entry points, but new development should increasingly use smaller task branches.

For example, Member 3 should prefer:

```text
feature/baseline-lru
feature/baseline-continuum
```

over putting every baseline change into one long-lived `feature/baseline` branch.

---

## 3. Before Starting a New Task

Switch to `main`:

```bash
git checkout main
```

Pull the latest version:

```bash
git pull origin main
```

Check the workspace:

```bash
git status
```

Prefer starting from a clean tree:

```text
nothing to commit, working tree clean
```

Then create a branch from the latest `main`.

Example:

```bash
git checkout -b feature/baseline-continuum
```

Do not continue long-term development on a stale branch that has fallen far behind `main`.

---

## 4. Branch Naming

### Feature code

```text
feature/<task-name>
```

Examples:

```text
feature/baseline-lru
feature/baseline-continuum
feature/cost-aware-policy
feature/workload-generator
feature/metrics-export
```

### Documentation

```text
docs/<task-name>
```

Examples:

```text
docs/related-work
docs/presentation
docs/baseline-analysis
```

### Bug fixes

```text
fix/<bug-name>
```

Example:

```text
fix/cache-counter
```

### Experiments

```text
experiment/<name>
```

Examples:

```text
experiment/cache-pressure
experiment/policy-comparison
```

Avoid vague branch names such as:

```text
test
new
temp
mybranch
final
final2
member3-new
```

---

## 5. One Branch, One Task

A branch should contain one reviewable unit of work.

For example:

```text
feature/baseline-continuum
```

should contain only Continuum-baseline-related changes.

Do not casually mix unrelated work such as:

- major README changes;
- refactoring another member's module;
- workload changes;
- plotting scripts;
- presentation changes;
- unrelated bug fixes.

Large mixed PRs are difficult to review and merge safely.

---

## 6. Commit Conventions

Use small, descriptive commits.

Recommended examples:

```text
feat: implement LRU baseline adapter
feat: add continuum retention policy
fix: correct cache block accounting
test: add eviction policy unit tests
docs: document baseline reproduction scope
refactor: extract policy adapter interface
chore: update experiment config
```

Avoid messages such as:

```text
update
修改
aaa
final
finish
test123
改好了
```

A commit should normally correspond to one logical change.

---

## 7. Check Before Committing

Run:

```bash
git status
git diff
```

Ensure that accidental files are not being committed.

Never commit:

- model weights;
- Hugging Face cache;
- Docker data;
- large raw logs;
- profiling dumps;
- temporary experiment files;
- secrets or tokens;
- unnecessary IDE-local configuration.

In particular, do not commit large model artifacts such as:

```text
*.safetensors
large *.bin files
.cache/
model directories
HF cache
```

---

## 8. Push

For the first push of a branch:

```bash
git push -u origin <branch-name>
```

Example:

```bash
git push -u origin feature/baseline-continuum
```

After that:

```bash
git push
```

---

## 9. Merge Through Pull Requests

Do not manually merge feature work into `main` and push it directly.

Use GitHub Pull Requests for formal changes.

PR titles should be clear, for example:

```text
Implement vLLM LRU baseline
Reproduce Continuum-style retention baseline
Add repeated-prefix workload generator
Add policy evaluation metrics
```

A PR description should include at least:

```text
What:
What changed?

Why:
Why is this needed?

Tests:
What was run?

Limitations:
What remains incomplete?
```

---

## 10. Keep PRs Reviewable

Prefer:

```text
PR 1: policy interface
PR 2: LRU baseline
PR 3: Continuum-style baseline
```

instead of one PR containing:

```text
baseline + workload + experiments + plots + README + optimization
```

If a PR spans thousands of lines and multiple independent modules, split it when possible.

---

## 11. Sync With `main` During Development

If `main` changes while you are working:

```bash
git checkout main
git pull origin main

git checkout <your-branch>
git merge main
```

Resolve conflicts, then:

```bash
git add .
git commit
git push
```

Rebase is also valid, but members who are not comfortable with Git should prefer merging `main` into the task branch to reduce risk.

---

## 12. Avoid Force Pushes

Do not normally use:

```bash
git push --force
```

Never force-push casually to:

- `main`;
- another member's branch;
- a shared branch.

If history rewriting is absolutely necessary on your own unreviewed branch, prefer:

```bash
git push --force-with-lease
```

If you are not confident about this operation, do not use it.

---

## 13. Respect Module Ownership

Work primarily within your assigned module and collaborate through stable interfaces.

Examples:

- Member 3 should not silently rewrite Member 5's workload system while implementing a baseline.
- Member 5 should not embed baseline-specific logic inside workload generation.
- If a public interface is insufficient, propose an interface change rather than directly depending on another module's internals.

If a cross-module modification is necessary, explain it explicitly in the PR and involve the corresponding owner.

---

## 14. Baselines and Optimization Must Share the Same Runtime Path

The project should preserve a common backend structure:

```text
vLLM backend
      ↓
common policy adapter
      ↓
├── LRU
├── Continuum-style
└── Cost-Aware
```

Members 3 and 4 must not create separate execution paths that make baseline and optimized methods incomparable.

If the adapter is insufficient, update the shared interface first.

---

## 15. Separate Experiment Code From Large Experiment Outputs

Experiment code belongs in version control, for example:

```text
benchmarks/
scripts/
configs/
```

Small summarized outputs may be stored in:

```text
results/
```

Do not commit large raw artifacts such as:

- multi-gigabyte traces;
- profiling dumps;
- model caches;
- huge JSON logs.

Git should retain the information required to reproduce the experiment:

- configurations;
- scripts;
- small CSV summaries;
- generated figures when appropriate;
- summarized results;
- reproduction instructions.

---

## 16. Member 2 — Related Work

Recommended workflow:

```text
latest main
↓
docs/related-work-<topic>
↓
modify docs/
↓
PR
```

Do not modify policy implementation unless explicitly coordinated.

If literature review suggests that the selected baseline is inappropriate, document the concern first and let the team freeze the new scope before implementation changes.

---

## 17. Member 3 — Baseline Reproduction

Recommended branch structure:

```text
docs/baseline-freeze
feature/baseline-lru
feature/baseline-continuum
```

Recommended order:

```text
freeze reproduction scope
↓
LRU baseline
↓
strong baseline
↓
tests
```

Do not start implementing a personal interpretation of a paper before documenting:

- what the original method does;
- what part will be reproduced;
- what part is adapted to vLLM;
- what cannot be reproduced faithfully.

---

## 18. Member 4 — Optimization

Prefer working in a branch such as:

```text
feature/cost-aware-policy
```

Do not make large shared-runtime changes before the baseline interface is stable.

The proposed optimization must run through the same policy interface as the baselines.

---

## 19. Member 5 — Workload and Benchmark

Main areas include:

```text
workload/
benchmarks/
configs/
```

Suggested branches:

```text
feature/workload-prefix-reuse
feature/workload-cache-pressure
feature/benchmark-runner
```

Do not hard-code one specific baseline's internal behavior into the workload layer.

---

## 20. Member 6 — Evaluation

Main areas include:

```text
benchmarks/
results/
scripts/
```

Example branches:

```text
feature/evaluation-metrics
experiment/lru-vs-continuum
experiment/final-policy-comparison
```

Formal experiments should record at least:

```text
Git commit SHA
vLLM version
model
GPU
config
workload
seed
policy
```

Without this metadata, the result is not reproducible.

---

## 21. Member 7 — Presentation

Use a documentation-oriented branch such as:

```text
docs/presentation
```

Do not modify core experiment code in the presentation branch.

If a result appears inconsistent, report it to the corresponding implementation or evaluation owner rather than editing the result manually.

---

## 22. Conflict Resolution

Do not blindly resolve conflicts with commands such as:

```bash
git checkout --theirs .
git checkout --ours .
```

First inspect:

```bash
git status
```

Resolve files individually.

If a conflict is inside another member's core module, coordinate with that member before choosing one side.

---

## 23. Do Not Commit Unverified Experimental Claims

A program running successfully is not the same as a validated performance result.

For example:

```text
program runs
```

is not sufficient evidence for:

```text
Our policy improves performance.
```

Performance claims should only be added after formal evaluation.

---

## 24. Current Project Phase

The project has completed:

```text
Phase 0 — Backend & Architecture Validation
COMPLETE
```

The real backend is pinned to:

```text
vLLM 0.27.1
```

Validated items include:

```text
GPU inference
APC cache hit
controlled cache pressure
cached-block eviction
BlockPool integration point
```

The project is now entering:

```text
Phase 1 — Baseline Reproduction
```

New work should therefore start from the latest `main`, not from stale long-lived branches created before Phase 0 was completed.

---

## Final Three Rules

```text
1. Do not develop directly on main.
2. One branch should represent one task.
3. Formal changes merge through Pull Requests.
```

If you are unsure where a change belongs, check `docs/team-responsibilities.md` before starting the branch.
