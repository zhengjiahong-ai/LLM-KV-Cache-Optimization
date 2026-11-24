"""Compute turn-based Continuum memoryfulness from the complete Nebius archive."""
from collections import Counter

import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq


def moments(lengths, include_end=True):
    """Sufficient statistics of equally weighted ordinal snapshots per Program."""
    n = np.asarray(lengths, dtype=np.float64)
    m = n if include_end else n - 1
    sx = m * (m + 1) / 2
    sxx = sx * (2 * m + 1) / 3
    return np.stack((m, sx, m*n - sx, sxx, m*n*n - 2*n*sx + sxx, n*sx - sxx), axis=-1)


def eta(total):
    n, sx, sy, sxx, syy, sxy = np.moveaxis(np.asarray(total, dtype=float), -1, 0)
    if np.any(n <= 0):
        raise ValueError("Empty snapshot set")
    variance = (n*sxx - sx*sx) * (n*syy - sy*sy)
    if np.any(variance <= 0):
        raise ValueError("Degenerate correlation")
    return -(n*sxy - sx*sy) / np.sqrt(variance)


def score(frame, extensions=0, include_end=True, bootstrap=False):
    n = frame.turns.to_numpy() + extensions * frame.censored.to_numpy()
    matrix = moments(n, include_end)
    result = {"attempts": len(n), "issues": frame.issue.nunique(),
              "observed_turn_sum": int(frame.turns.sum()), "snapshots": int(matrix[:, 0].sum()),
              "mean_turns": float(frame.turns.mean()),
              "turn_p50_p90_p95": np.quantile(frame.turns, [.5, .9, .95]).tolist(),
              "eta": float(eta(matrix.sum(axis=0))),
              "attempt_weighted_eta": float(eta((matrix / matrix[:, :1]).sum(axis=0)))}
    if bootstrap:
        items = pd.DataFrame(matrix).groupby(frame.issue.to_numpy()).sum().to_numpy()
        rng = np.random.default_rng(251102230)
        sampled = [eta(items[rng.integers(len(items), size=len(items))].sum(axis=0))
                   for _ in range(1000)]
        result["issue_cluster_percentile_95"] = np.quantile(sampled, [.025, .975]).tolist()
    return result


def census(parquet):
    rows = []
    errors = Counter()
    file = pq.ParquetFile(parquet)
    for batch in file.iter_batches(
        batch_size=256, columns=["repo", "instance_id", "trajectory_id", "exit_status", "trajectory"]
    ):
        trajectory = batch.column("trajectory")
        if trajectory.null_count:
            raise ValueError("Null trajectory")
        messages = pc.list_flatten(trajectory)
        parents = pc.list_parent_indices(trajectory).to_numpy(zero_copy_only=False)
        roles = messages.field("role")
        if roles.null_count:
            raise ValueError("Null role")
        assistant = pc.equal(roles, "assistant").to_numpy(zero_copy_only=False)
        turns = np.bincount(parents[assistant], minlength=len(batch))
        call_lists = messages.field("tool_calls")
        names = pc.list_flatten(call_lists).field("function").field("name")
        if names.null_count:
            raise ValueError("Null tool name")
        call_parents = parents[pc.list_parent_indices(call_lists).to_numpy(zero_copy_only=False)]
        tools = np.bincount(call_parents, minlength=len(batch))
        bash = np.bincount(call_parents[pc.equal(names, "execute_bash").to_numpy(zero_copy_only=False)],
                           minlength=len(batch))
        editor = np.bincount(
            call_parents[pc.equal(names, "str_replace_editor").to_numpy(zero_copy_only=False)],
            minlength=len(batch),
        )
        identifiers = [batch.column(name).to_pylist()
                       for name in ("repo", "instance_id", "trajectory_id", "exit_status")]
        for repo, issue, attempt, status, n, calls, b, e in zip(
            *identifiers, turns, tools, bash, editor, strict=True
        ):
            if not all((repo, issue, attempt, status)) or n < 2:
                raise ValueError("Missing identity/outcome or invalid turn count")
            if status == "submit":
                end = "submit"
            elif "reached maximum iteration" in status or n >= 100:
                end = "step_limit"
            else:
                end = "other_interruption"
            if end != "submit":
                errors[status] += 1
            rows.append((repo, issue, attempt, end, n, calls, b, e))
    frame = pd.DataFrame(rows, columns=["repo", "issue", "attempt", "end",
                                        "turns", "calls", "bash", "editor"])
    if len(frame) != file.metadata.num_rows or frame.attempt.duplicated().any():
        raise ValueError("Incomplete census or repeated attempt identity")
    if frame.groupby("issue").repo.nunique().gt(1).any():
        raise ValueError("An issue maps to more than one repository")
    frame["censored"] = frame.end.ne("submit")
    frame["tool_mix"] = np.select([frame.bash > frame.editor, frame.bash < frame.editor],
                                  ["bash_more", "editor_more"], default="tie")
    frame["length"] = pd.cut(frame.turns, [0, 25, 50, 75, 99, np.inf],
                             labels=["<=25", "26-50", "51-75", "76-99", "100+"])
    shrink = frame.repo.value_counts()
    frame["repo_group"] = frame.repo.where(frame.repo.isin(shrink.head(5).index), "other")
    submitted = frame.loc[~frame.censored]
    result = {
        "rows": len(frame), "issue_count": frame.issue.nunique(), "repo_count": frame.repo.nunique(),
        "interruption_statuses": dict(errors),
        "observed_at_100": {k: int(v) for k, v in frame.loc[frame.turns.eq(100)].end.value_counts().items()},
        "turn_tool_count_correlation": float(frame.turns.corr(frame.calls)),
        "archive_endpoint_eta": score(frame, bootstrap=True),
        "submitted_eta": score(submitted, bootstrap=True),
        "submitted_preterminal_eta": score(submitted, include_end=False),
        "submitted_under100_eta": score(submitted.loc[submitted.turns.lt(100)]),
        "exclude_step_limit_endpoint_eta": score(frame.loc[frame.end.ne("step_limit")]),
        "hypothetical_extension": {d: score(frame, extensions=d) for d in (10, 25, 50)},
        "by_end_observed_endpoint": {k: score(g) for k, g in frame.groupby("end")},
        "submitted_by_length": {k: score(g) for k, g in submitted.groupby("length", observed=True)},
        "submitted_by_tool_mix": {k: score(g) for k, g in submitted.groupby("tool_mix")},
        "submitted_by_repository": {k: score(g) for k, g in submitted.groupby("repo_group")},
        "remaining_by_checkpoint": {
            k: {end: {"attempts": len(g), "mean_visible_remaining": float((g.turns-k).mean())}
                for end, g in frame.loc[frame.turns.ge(k)].groupby("end")}
            for k in (16, 24, 32, 64, 90, 99)
        },
    }
    return frame, result
