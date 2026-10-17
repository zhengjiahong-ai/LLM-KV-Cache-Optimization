"""H1 evidence: inside a chain, is native LRU already ordering blocks deepest-first?

Backs the 294/294 statement used by the joint design document.

Definition used here, stated so it can be re-run:

  chain window = one candidate entry inside one ``FORCED_RELEASE_DECISION``.
                 ``k`` = index within ``candidates[].block_ids`` (ascending; the
                 payload lists ``block_ids`` in ascending block-id order while
                 ``initially_reclaimable_block_ids`` is the reverse/tail-first
                 order, so ascending is the prefix-order reading).
  rho          = Spearman(k, native_lru_rank of that block), with ranks taken
                 from the decision's ``original_free_queue``.

  rho < 0  => deeper blocks have SMALLER rank => native LRU already evicts the
             deeper block first => no room for a depth rule inside a chain.
  rho > 0  => shallower blocks are colder  => a depth rule could help.

Also prints, for a few ordering-relevant decisions, the rank-ordered
``(block_id, lru_rank, has_block_hash)`` sequence so the free-queue invariant
below is auditable by eye:

  native puts every hashless block at ranks ``{0..k-1}``; hashed blocks follow.

Usage::

    python scripts/probes/h1_lru_monotonicity.py <runs-dir> [--strict]
    KVOPT_H1_RUNS=<runs-dir> python scripts/probes/h1_lru_monotonicity.py

The artifacts are not committed; only this script is.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

DOCUMENTED = {
    "decisions": 87,
    "order_relevant": 54,
    "windows": 294,
    "rho_exactly_minus_one": 294,
}


def resolve_runs(argv: list[str]) -> Path:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if args:
        return Path(args[0]).resolve()
    env = os.environ.get("KVOPT_H1_RUNS")
    if env:
        return Path(env).resolve()
    raise SystemExit(
        "usage: h1_lru_monotonicity.py <runs-dir> [--strict]\n"
        "       (or set KVOPT_H1_RUNS)"
    )


def spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=values.__getitem__)
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2.0 + 1.0
            for t in range(i, j + 1):
                out[order[t]] = average
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    numerator = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return None if dx == 0 or dy == 0 else numerator / (dx * dy)


def main() -> int:
    runs = resolve_runs(sys.argv)
    strict = "--strict" in sys.argv
    if not runs.is_dir():
        raise SystemExit(f"not a directory: {runs}")

    decisions = 0
    windows = 0
    rhos: list[float] = []
    lagging = 0
    leading = 0
    ref_cnt_present = 0
    queue_rows = 0
    order_relevant = 0
    snapshots: list[dict] = []

    for path in sorted(runs.rglob("events.jsonl")):
        try:
            events = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            continue
        forced = [
            e for e in events if e.get("event_type") == "FORCED_RELEASE_DECISION"
        ]
        if not forced:
            continue
        payload = forced[-1].get("payload") or {}
        queue = payload.get("original_free_queue") or []
        candidates = payload.get("candidates") or []
        required = payload.get("required_blocks")
        if not queue or not candidates or not isinstance(required, int):
            continue
        decisions += 1

        rank_of: dict[int, int] = {}
        has_of: dict[int, bool] = {}
        for row in queue:
            queue_rows += 1
            if "ref_cnt" in row:
                ref_cnt_present += 1
            block_id = row.get("block_id")
            rank = row.get("native_lru_rank")
            if block_id is None or rank is None:
                continue
            rank_of[int(block_id)] = int(rank)
            has_of[int(block_id)] = bool(row.get("has_block_hash"))

        # ---- reviewable snapshot for ordering-relevant decisions only ----
        if required < len(rank_of):
            order_relevant += 1
            if len(snapshots) < 3:
                ordered = sorted(rank_of.items(), key=lambda kv: kv[1])
                snapshots.append(
                    {
                        "run_id": str(forced[-1].get("run_id")),
                        "event_index": int(forced[-1].get("event_index", -1)),
                        "required_blocks": required,
                        "queue_len": len(ordered),
                        "first_12": [
                            (bid, rk, has_of.get(bid)) for bid, rk in ordered[:12]
                        ],
                        "n_hashless": sum(1 for _, h in has_of.items() if not h),
                        "first_hashed_rank": next(
                            (rk for bid, rk in ordered if has_of.get(bid)), None
                        ),
                    }
                )

        # ---- chain windows ----
        for candidate in candidates:
            ids = [int(b) for b in (candidate.get("block_ids") or [])]
            ks, rs = [], []
            for k, block_id in enumerate(ids):
                if block_id in rank_of:
                    ks.append(float(k))
                    rs.append(float(rank_of[block_id]))
            if len(ks) < 3:
                continue
            rho = spearman(ks, rs)
            if rho is None:
                continue
            windows += 1
            rhos.append(rho)
            if rho > 0:
                lagging += 1
            elif rho < 0:
                leading += 1

    print("=" * 78)
    print("0. PROVENANCE")
    print("=" * 78)
    print(f"decisions                                     : {decisions}")
    print(f"queue rows                                    : {queue_rows}")
    print(f"  rows carrying a `ref_cnt` field             : {ref_cnt_present}"
          "  (0 => ref_cnt is NOT persisted in H1)")
    print(f"ordering-relevant decisions (required<queue)  : {order_relevant}")

    print()
    print("=" * 78)
    print("1. CHAIN WINDOWS: rho = Spearman(chain position k, native_lru_rank)")
    print("=" * 78)
    print(f"windows measured (>=3 comparable blocks)      : {windows}")
    minus_one = sum(1 for v in rhos if v <= -0.9999)
    plus_one = sum(1 for v in rhos if v >= 0.9999)
    if windows:
        ordered_rhos = sorted(rhos)
        print(f"  rho min {ordered_rhos[0]:.4f}  median "
              f"{statistics.median(rhos):.4f}  mean {statistics.fmean(rhos):.4f}"
              f"  max {ordered_rhos[-1]:.4f}")
        print("  rho < 0 (deeper = colder => LRU already deep-first) : "
              f"{leading} = {100 * leading / windows:.1f}%")
        print("  rho > 0 (shallow = colder => room for a depth rule) : "
              f"{lagging} = {100 * lagging / windows:.1f}%")
        print(f"  exactly -1.0000 : {minus_one}")
        print(f"  exactly +1.0000 : {plus_one}")
    else:
        print("  => no comparable window: chain identity/position NOT usable here")

    print()
    print("=" * 78)
    print("2. REVIEWABLE FREE-QUEUE SNAPSHOT (rank ascending = eviction order)")
    print("=" * 78)
    for snapshot in snapshots:
        print(f"  run_id={snapshot['run_id']}"
              f" event_index={snapshot['event_index']}")
        print(f"    required_blocks={snapshot['required_blocks']}"
              f" queue_len={snapshot['queue_len']}"
              f" hashless_in_queue={snapshot['n_hashless']}"
              f" first_hashed_rank={snapshot['first_hashed_rank']}")
        print("    coldest 12 as (block_id, lru_rank, has_block_hash):")
        print(f"      {snapshot['first_12']}")

    if strict:
        assert decisions == DOCUMENTED["decisions"], decisions
        assert order_relevant == DOCUMENTED["order_relevant"], order_relevant
        assert windows == DOCUMENTED["windows"], windows
        assert minus_one == DOCUMENTED["rho_exactly_minus_one"], minus_one
        assert plus_one == 0, plus_one
        print("\nSTRICT: documented counts reproduced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
