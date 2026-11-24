"""Counterfactual loss for logical, parent-chained prefix blocks.

The caller supplies a synthetic initial state and fixed future request order.
No adapter, runtime queue, capacity scheduler, or policy timestamps are inferred.
"""
from dataclasses import dataclass
from itertools import combinations


def make_paths(prompts, block_size):
    """Map complete blocks to exact (parent, tokens) identities for this scenario."""
    if block_size < 1:
        raise ValueError("Block size must be positive")
    nodes = {}
    paths = []
    for prompt in prompts:
        parent = 0
        path = []
        for position in range(0, len(prompt) - block_size + 1, block_size):
            key = (parent, tuple(prompt[position:position + block_size]))
            parent = nodes.setdefault(key, len(nodes) + 1)
            path.append(parent)
        paths.append(tuple(path))
    return paths


def suffix_loss(paths, removed):
    """Static unit-weight current-chain cost in blocks, including all memberships."""
    return sum(
        len(path) - next((i for i, block in enumerate(path) if block in removed), len(path))
        for path in paths
    )


@dataclass(frozen=True)
class FutureRequest:
    baseline_hits: int
    victim_depths: dict[int, int]


def prepare(initial, future, candidates):
    """Compute baseline contiguous hits once and index candidate blocks by depth."""
    resident = set(initial)
    if not candidates or not candidates <= resident:
        raise ValueError("Candidates must form a nonempty subset of the initial cache")
    requests = []
    for path in future:
        hits = next((i for i, block in enumerate(path) if block not in resident), len(path))
        requests.append(FutureRequest(
            hits, {block: i for i, block in enumerate(path) if block in candidates}
        ))
        resident.update(path)
    return requests


def loss_by_request(requests, victims):
    """Measure logical contiguous hit loss with refill after every request and a single initial intervention."""
    remaining = set(victims)
    result = []
    for request in requests:
        lost_depths = remaining.intersection(request.victim_depths)
        hit = min(request.baseline_hits,
                  min((request.victim_depths[b] for b in lost_depths),
                      default=request.baseline_hits))
        result.append(request.baseline_hits - hit)
        remaining.difference_update(lost_depths)
    return result


def evaluate(current, future, ranked, budget, alternate_ranked=None):
    """Evaluate all equal-budget subsets, guarding the predecision feature boundary."""
    if len(set(ranked)) != len(ranked) or not 0 < budget < len(ranked):
        raise ValueError("Expected unique candidates and multiple feasible victim sets")
    initial = set().union(*map(set, current))
    choices = [frozenset(items) for items in combinations(ranked, budget)]
    requests = prepare(initial, future, set(ranked))
    static = {choice: suffix_loss(current, choice) for choice in choices}
    singleton = {block: suffix_loss(current, {block}) for block in ranked}
    future_losses = {choice: sum(loss_by_request(requests, choice)) for choice in choices}
    warm_shallow = choices[0]
    if alternate_ranked is not None and (
        len(alternate_ranked) != len(ranked) or set(alternate_ranked) != set(ranked)
    ):
        raise ValueError("Alternate ordering must use the same candidate set")
    alternate = frozenset(alternate_ranked[:budget]) if alternate_ranked is not None else warm_shallow
    greedy = frozenset()
    marginals = []
    for _ in range(budget):
        prior = suffix_loss(current, greedy)
        deltas = {
            block: suffix_loss(current, greedy | {block}) - prior
            for block in ranked if block not in greedy
        }
        marginals.append(list(deltas.values()))
        greedy = greedy | {min(deltas, key=deltas.__getitem__)}
    exact_static = min(choices, key=static.__getitem__)
    optimal = min(choices, key=future_losses.__getitem__)
    worst = max(future_losses.values())
    best = future_losses[optimal]
    comparable = agreements = 0
    for left, right in combinations(choices, 2):
        actual = future_losses[left] - future_losses[right]
        predicted = static[left] - static[right]
        if actual:
            comparable += 1
            agreements += (1 if actual * predicted > 0 else .5 if predicted == 0 else 0)
    return {
        "legal_sets": len(choices),
        "warm_shallow": future_losses[warm_shallow],
        "greedy": future_losses[greedy],
        "geometry_exact": future_losses[exact_static],
        "oracle": best,
        "warm_deep_regret": future_losses[alternate] - best,
        "victim_loss_span": worst - best,
        "warm_shallow_regret": future_losses[warm_shallow] - best,
        "greedy_regret": future_losses[greedy] - best,
        "geometry_exact_regret": future_losses[exact_static] - best,
        "greedy_diverges": greedy != warm_shallow,
        "geometry_exact_diverges": exact_static != warm_shallow,
        "oracle_diverges": optimal != warm_shallow,
        "greedy_proxy_gap": static[greedy] - static[exact_static],
        "static_range": max(static.values()) - min(static.values()),
        "max_initial_marginal": max(marginals[0]),
        "min_initial_marginal": min(marginals[0]),
        "zero_second_marginals": marginals[1].count(0) if budget > 1 else None,
        "zero_marginal_pair_rate": (
            sum(static[c] == max(singleton[b] for b in c) for c in choices)
            / len(choices) if budget == 2 else None
        ),
        "rank_agreement": agreements / comparable if comparable else None,
    }
