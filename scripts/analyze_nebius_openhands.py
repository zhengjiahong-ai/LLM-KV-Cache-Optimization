"""Describe the pinned Nebius OpenHands Parquet and reconstruct Qwen prompt prefixes."""
import argparse
from array import array
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from hashlib import blake2b
import json
import os
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from jinja2.sandbox import ImmutableSandboxedEnvironment
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kvopt.profiling.continuum_w1c_report import _lcp

BLOCKS = (16, 32, 64, 128)
BANDS = ["1-10", "11-25", "26-50", "51-75", "76-99", "100+"]
GEN = "<|im_start|>assistant\n"
MARK = "\x00NEBIUS_ASSISTANT_BOUNDARY\x00"
PERCENTILES = (0.1, 0.5, 0.9, 0.95, 0.99)


def stats(values):
    values = np.asarray(values)
    if not len(values):
        return {"n": 0}
    return {
        "n": len(values), "min": float(values.min()), "mean": float(values.mean()),
        **{f"p{int(q * 100)}": float(v)
           for q, v in zip(PERCENTILES, np.quantile(values, PERCENTILES))},
        "max": float(values.max()),
    }


def remove_arrow_nulls(value):
    if isinstance(value, dict):
        return {k: remove_arrow_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [remove_arrow_nulls(v) for v in value]
    return value


def band(turns):
    return BANDS[sum(turns > edge for edge in (10, 25, 50, 75, 99))]


class Reconstruction:
    def __init__(self, directory):
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        cfg = json.loads((directory / "tokenizer_config.json").read_bytes())
        source = cfg["chat_template"]
        anchor = "{%- for message in loop_messages %}"
        if source.count(anchor) != 1:
            raise ValueError("Expected the pinned Qwen chat template")
        environment = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
        environment.filters["tojson"] = lambda obj: json.dumps(obj, ensure_ascii=False)
        self.template = environment.from_string(source)
        self.marked = environment.from_string(source.replace(
            anchor, anchor + "{%- if message.role == 'assistant' %}{{ marker }}{%- endif %}"
        ))
        self.schemas = {}
        self.headers = {}
        self.systems = {}
        self.tasks = {}
        self.first_prompts = {}
        self.generation = self.encode(GEN)

    def encode(self, text):
        return self.tokenizer.encode(text, add_special_tokens=False).ids

    def messages(self, messages, tools):
        # Assistant boundaries begin with the special token <|im_start|>.
        # The preceding rendered message closes before it.
        rendered = self.marked.render(
            messages=messages, tools=tools, add_generation_prompt=False, marker=MARK
        )
        segments = rendered.split(MARK)
        return segments[:-1]

    def header(self, messages, tools):
        system = messages[:1] if messages[0]["role"] == "system" else []
        system_text = system[0]["content"] if system else None
        schema_key = json.dumps(tools, ensure_ascii=False)
        schema_id = self.schemas.setdefault(schema_key, len(self.schemas))
        key = (system_text, schema_id)
        if key not in self.headers:
            text = self.template.render(
                messages=system or [{"role": "user", "content": ""}],
                tools=tools, add_generation_prompt=False,
            )
            if not system:
                text = text.removesuffix("<|im_start|>user\n<|im_end|>\n")
            self.headers[key] = (len(self.headers), len(self.encode(text)))
        system_only = self.systems.get(system_text)
        if system_only is None:
            text = self.template.render(
                messages=system or [{"role": "user", "content": ""}],
                tools=[], add_generation_prompt=False,
            )
            system_only = (len(self.systems), len(self.encode(text)) if system else 0)
            self.systems[system_text] = system_only
        return self.headers[key], schema_id, system_only

    def first_prompt(self, segment):
        if segment not in self.first_prompts:
            self.first_prompts[segment] = array("I", self.encode(segment) + self.generation)
        return self.first_prompts[segment]

    def verify(self, messages, tools, segments):
        prefix = []
        boundaries = [i for i, message in enumerate(messages) if message["role"] == "assistant"]
        for segment, index in zip(segments, boundaries, strict=True):
            prefix.extend(self.encode(segment))
            if index > 0:
                full = self.template.render(
                    messages=messages[:index], tools=tools, add_generation_prompt=True
                )
                if prefix + self.generation != self.encode(full):
                    raise ValueError(f"Segmented encoding differs at message {index}")


def scan(parquet, tokenizer_dir, groups):
    reconstruction = Reconstruction(tokenizer_dir)
    file = pq.ParquetFile(parquet)
    offset = sum(file.metadata.row_group(g).num_rows for g in range(groups[0]))
    row_count = sum(file.metadata.row_group(g).num_rows for g in groups)
    metadata = []
    turns = []
    initial = []
    audit = Counter()
    missing = Counter()
    roles = Counter()
    tools_by_outcome = defaultdict(Counter)
    tool_shapes = Counter()
    contribution = Counter()
    ids = []
    fingerprints = []
    for chunk in file.iter_batches(batch_size=48, row_groups=groups):
        prepared = []
        snippets = []
        for record in chunk.to_pylist():
            number = len(metadata)
            identity = record["trajectory_id"]
            issue = record["instance_id"]
            repo = record["repo"]
            resolved = record["resolved"]
            status = record["exit_status"]
            ids.append(identity)
            for field, value in record.items():
                if value is None:
                    missing[field] += 1
            messages = record["trajectory"] or []
            tools = remove_arrow_nulls(record["tools"] or [])
            counts = Counter()
            canonical = []
            requests = []
            structural = []
            previous = -1
            awaiting_result = set()
            known_calls = set()
            valid = bool(messages) and messages[0]["role"] == "system"
            if not valid:
                audit["empty_or_non_system_start"] += 1
            for index, message in enumerate(messages):
                role = message["role"]
                roles[role] += 1
                content = message["content"]
                calls = message["tool_calls"] or []
                if content is None:
                    audit[f"null_content_{role}"] += 1
                if role == "assistant":
                    requests.append(index)
                    new_messages = index - previous if previous >= 0 else index
                    previous_tool_calls = (
                        sum(counts.values()) - sum(previous_counts.values()) if previous >= 0 else 0
                    )
                    structural.append((new_messages, previous_tool_calls))
                    previous_counts = counts.copy()
                    previous = index
                normalized_calls = []
                for call in calls:
                    function = call.get("function") or {}
                    name = function.get("name") or "<missing>"
                    counts[name] += 1
                    call_id = call.get("id")
                    if call_id is not None:
                        if call_id in known_calls:
                            audit["duplicate_tool_call_id"] += 1
                        known_calls.add(call_id)
                        awaiting_result.add(call_id)
                    else:
                        audit["call_missing_id"] += 1
                    args = function.get("arguments")
                    try:
                        arguments = json.loads(args)
                        if not isinstance(arguments, dict):
                            raise ValueError("Tool arguments must be an object")
                    except (ValueError, TypeError):
                        valid = False
                        audit["non_object_tool_arguments"] += 1
                        arguments = {}
                    normalized_calls.append({"function": {"name": name, "arguments": arguments}})
                if role == "tool":
                    result_id = message["tool_call_id"]
                    if result_id not in awaiting_result:
                        audit["result_without_open_call"] += 1
                    awaiting_result.discard(result_id)
                canonical.append({"role": role, "content": content or "",
                                  "tool_calls": normalized_calls})
            audit["tool_calls_without_result"] += len(awaiting_result)
            audit["attempts_with_tool_call_without_result"] += bool(awaiting_result)
            audit["empty_patch"] += record["model_patch"] == ""
            audit["nonbinary_resolved"] += resolved not in (0, 1)
            audit["no_assistant"] += not requests
            audit["tail_nonassistant"] += bool(requests and requests[-1] != len(messages) - 1)
            audit["multi_tool_assistant_messages"] += sum(
                len(m["tool_calls"] or []) > 1 for m in messages if m["role"] == "assistant"
            )
            audit["assistant_without_calls"] += sum(
                not m["tool_calls"] for m in messages if m["role"] == "assistant"
            )
            # A single trajectory fingerprint for duplicate detection. Tool call IDs are
            # intentionally omitted because providers can generate new IDs for the same text.
            fingerprint = blake2b(
                json.dumps([repo, issue, canonical, tools], ensure_ascii=False,
                           sort_keys=True, separators=(",", ":")).encode("utf-8"),
                digest_size=16,
            ).digest()
            fingerprints.append(fingerprint)
            tools_by_outcome[resolved].update(counts)
            schema_names = tuple(t.get("function", {}).get("name", "") for t in tools)
            tool_shapes["|".join(schema_names)] += 1
            n = len(requests)
            metadata.append({
                "repo": repo, "issue": issue, "status": status, "resolved": resolved,
                "turns": n, "stage": band(n), "calls": sum(counts.values()),
                **{f"calls_{key}": counts[key] for key in schema_names},
            })
            if not (valid and requests and requests[0] > 0):
                audit["attempts_without_token_reconstruction"] += 1
                continue
            segments = reconstruction.messages(canonical, tools)
            if len(segments) != n or any(
                not segment.startswith("<|im_start|>assistant") for segment in segments[1:]
            ):
                raise ValueError("Unexpected assistant boundary")
            if offset + number < 12 or ((offset + number) % 4096 == 0):
                reconstruction.verify(canonical, tools, segments)
                audit["attempts_checked_against_direct_tokenization"] += 1
            (header_id, header_tokens), schema_id, (system_id, system_tokens) = (
                reconstruction.header(canonical, tools)
            )
            start = len(snippets)
            snippets.extend(segments[1:])
            initial_ids = reconstruction.first_prompt(segments[0])
            task = next((m["content"] for m in canonical if m["role"] == "user"), None)
            task_id = reconstruction.tasks.setdefault(task, len(reconstruction.tasks)) if task is not None else None
            initial.append((number, initial_ids, header_id, header_tokens, schema_id, system_id, task_id))
            tool_chars = 0
            arguments_chars = 0
            reply_chars = 0
            other_chars = 0
            for left, right in zip(requests, requests[1:]):
                for message in messages[left:right]:
                    size = len(message["content"] or "")
                    if message["role"] == "tool":
                        tool_chars += size
                    elif message["role"] == "assistant":
                        reply_chars += size
                        arguments_chars += sum(
                            len((c.get("function") or {}).get("arguments") or "")
                            for c in message["tool_calls"] or []
                        )
                    else:
                        other_chars += size
            for name, count in zip(
                ("tool_result_content", "tool_call_arguments", "assistant_content", "other_content"),
                (tool_chars, arguments_chars, reply_chars, other_chars),
            ):
                contribution[name] += count
            prepared.append((number, start, n, structural, initial_ids, header_tokens,
                             system_tokens, tool_chars, arguments_chars))
        encodings = reconstruction.tokenizer.encode_batch_fast(snippets, add_special_tokens=False)
        gen = reconstruction.generation
        for (number, start, n, structural, initial_ids, header_tokens,
             system_tokens, tool_chars, arguments_chars) in prepared:
            meta = metadata[number]
            prompt = len(initial_ids)
            turns.append((number, 1, prompt, -1, -1, *structural[0]))
            for index in range(1, n):
                addition = encodings[start + index - 1].ids
                common = prompt - len(gen) + _lcp(gen, addition[:len(gen)] + gen)
                prompt += len(addition)
                turns.append((number, index + 1, prompt, common, len(addition), *structural[index]))
            meta.update(first_tokens=len(initial_ids), last_tokens=prompt, growth=prompt - len(initial_ids),
                        tool_result_chars=tool_chars, tool_argument_chars=arguments_chars,
                        first_header_tokens=header_tokens, system_only_tokens=system_tokens)
            if n > 1:
                meta["last_lcp"] = common
        if len(metadata) // 4096 != (len(metadata) - chunk.num_rows) // 4096:
            total = file.metadata.num_rows
            print(f"Rows {offset + 1:,}-{offset + row_count:,}: {len(metadata):,}/{row_count:,} of {total:,}",
                  flush=True)
    assert len(metadata) == row_count
    meta = pd.DataFrame(metadata, index=pd.RangeIndex(offset, offset + row_count))
    per_turn = pd.DataFrame(np.asarray(turns, dtype=np.int32), columns=[
        "row", "turn", "prompt", "lcp", "growth", "new_messages", "previous_calls",
    ])
    per_turn["row"] += offset
    counters = {
        "missing_cells": missing, "audit": audit, "roles": roles,
        "tool_schema_name_sequences": tool_shapes, "appended_content_characters": contribution,
    }
    identities = (
        [key for key, _ in sorted(reconstruction.schemas.items(), key=lambda item: item[1])],
        list(reconstruction.headers), list(reconstruction.systems), list(reconstruction.tasks),
    )
    return meta, per_turn, initial, counters, tools_by_outcome, ids, fingerprints, identities


def combine(parquet, tokenizer_dir, workers):
    file = pq.ParquetFile(parquet)
    groups = np.array_split(np.arange(file.num_row_groups).tolist(), min(workers, file.num_row_groups))
    work = [(parquet, tokenizer_dir, group.tolist()) for group in groups]
    if len(work) == 1:
        parts = [scan(*work[0])]
    else:
        with ProcessPoolExecutor(max_workers=len(work)) as pool:
            futures = [pool.submit(scan, *args) for args in work]
            parts = [future.result() for future in futures]
    metadata = []
    turns = []
    initial = []
    counters = defaultdict(Counter)
    tool_calls = defaultdict(Counter)
    ids = []
    fingerprints = []
    schemas, headers, systems, tasks = {}, {}, {}, {}
    for frame, per_turn, first, fields, calls, part_ids, part_fingerprints, keys in parts:
        metadata.append(frame)
        turns.append(per_turn)
        ids.extend(identity for identity in part_ids if identity is not None)
        fingerprints.extend(part_fingerprints)
        for name, counts in fields.items():
            counters[name].update(counts)
        for outcome, counts in calls.items():
            tool_calls[outcome].update(counts)
        schema_keys, header_keys, system_keys, task_keys = keys
        schema_map = [schemas.setdefault(key, len(schemas)) for key in schema_keys]
        header_map = []
        for system, schema in header_keys:
            key = (system, schema_map[schema])
            header_map.append(headers.setdefault(key, len(headers)))
        system_map = [systems.setdefault(key, len(systems)) for key in system_keys]
        task_map = [tasks.setdefault(key, len(tasks)) for key in task_keys]
        initial.extend(
            (int(frame.index[0]) + index, prompt, header_map[header], boundary, schema_map[schema],
             system_map[system], task_map[task] if task is not None else None)
            for index, prompt, header, boundary, schema, system, task in first
        )
    summary = {
        **counters, "tool_calls_by_resolved": dict(tool_calls),
        "duplicates": {
            "repeated_trajectory_id_extra_rows": len(ids) - len(set(ids)),
            "repeated_normalized_transcript_extra_rows": len(fingerprints) - len(set(fingerprints)),
        },
        "columns": file.schema_arrow.names,
        "distinct_normalized_tool_schemas": len(schemas),
        "distinct_system_and_tool_headers": len(headers),
        "distinct_system_prompts": len(systems),
    }
    return pd.concat(metadata), pd.concat(turns, ignore_index=True), initial, summary


def sharing(meta, initial, samples):
    rng = np.random.default_rng(35455389)
    index = {item[0]: item[1:] for item in initial}
    population = meta.loc[list(index), ["repo", "issue"]].dropna()
    result = {}
    for relation, group_by in [("different_repo", "repo"), ("same_repo_different_issue", "repo"),
                               ("same_issue", "issue")]:
        groups = list(population.groupby(group_by).indices.values())
        repos = population.repo.to_numpy()
        issues = population.issue.to_numpy()
        rows = population.index.to_numpy()
        sizes = np.asarray([len(group) for group in groups])
        if relation == "different_repo":
            weights = sizes * (len(rows) - sizes)
        elif relation == "same_issue":
            weights = sizes * (sizes - 1)
        else:
            weights = np.asarray([
                len(group)**2 - sum(n*n for n in Counter(issues[group]).values())
                for group in groups
            ])
        if not weights.sum():
            result[relation] = {"eligible_pairs": 0}
            continue
        chosen = rng.choice(len(groups), size=samples, p=weights / weights.sum())
        values = []
        for group_number in chosen:
            group = groups[group_number]
            while True:
                a = int(rng.choice(group))
                if relation == "different_repo":
                    b = int(rng.integers(len(rows)))
                    if repos[a] != repos[b]:
                        break
                else:
                    b = int(rng.choice(group))
                    if (a != b and relation == "same_issue") or issues[a] != issues[b]:
                        break
            left, header_a, boundary_a, schema_a, system_a, task_a = index[rows[a]]
            right, header_b, boundary_b, schema_b, system_b, task_b = index[rows[b]]
            common = _lcp(left, right)
            shared_header = header_a == header_b
            values.append((common, common / len(right), system_a == system_b, schema_a == schema_b,
                           shared_header, task_a == task_b, left == right,
                           max(0, common - boundary_a) if shared_header else 0))
        pairs = pd.DataFrame(values, columns=[
            "lcp", "ratio", "system_equal", "schema_equal", "header_equal",
            "first_user_equal", "first_prompt_equal", "beyond_equal_header",
        ])
        result[relation] = {
            "eligible_pairs": int(weights.sum() // 2), "sample_n": len(pairs),
            "lcp": stats(pairs.lcp), "current_prompt_fraction": stats(pairs.ratio),
            "beyond_equal_header": stats(pairs.loc[pairs.header_equal, "beyond_equal_header"]),
            **{c: float(pairs[c].mean()) for c in pairs if c.endswith("_equal")},
            **{f"aligned_{b}": stats((pairs.lcp // b) * b) for b in BLOCKS},
        }
    return result


def opportunities(meta, initial):
    # A trace-derived construction. Use the same invariant head and distinct first
    # user content, then hypothetically interleave two attempts before their last turns.
    # Within each pair, unique reusable tail sizes cannot include the common ancestor.
    # Equal-length tails can also be cut from the ends, at different prefix depths.
    pools = defaultdict(list)
    for index, ids, header_id, _, _, _, task in initial:
        item = meta.loc[index]
        if item.turns > 1 and task is not None:
            pools[header_id].append((index, ids, task, item.issue, int(item.last_lcp)))
    values = []
    for pool in pools.values():
        remaining = list(reversed(pool))
        pending = None
        while remaining:
            right = remaining.pop()
            if pending is None:
                pending = right
                continue
            left = pending
            if left[2] == right[2] or left[3] == right[3]:
                continue
            pending = None
            common = _lcp(left[1], right[1])
            if common >= min(len(left[1]), len(right[1])) - 3:
                continue
            a, b = (left[4] // 16) * 16, (right[4] // 16) * 16
            shared = common // 16 * 16
            if min(a, b) > shared:
                values.append((abs(a - b), min(a, b) - shared, max(a, b) - shared,
                               max(a, b) / min(a, b)))
    return {
        "pairs_with_two_distinct_aligned_suffixes": len(values),
        "pairs_with_different_prefix_depth": sum(row[0] > 0 for row in values),
        "pairs_with_two_256_block_suffixes": sum(row[1] >= 16 * 256 for row in values),
        **{name: stats([row[i] for row in values]) for i, name in enumerate(
            ("prefix_depth_gap", "smaller_exclusive_tail", "larger_exclusive_tail",
             "larger_to_smaller_prefix_depth")
        )},
    }


def summarize(meta, turns, initial, summary, samples, output):
    by_issue = meta.groupby(["repo", "issue"]).resolved.agg(
        attempts="size", resolved_attempts=lambda labels: int(labels.eq(1).sum())
    )
    by_issue.to_csv(output / "issue_attempts.csv")
    attempts = by_issue.attempts
    summary.update(
        trajectories=len(meta), repositories=int(meta.repo.nunique()),
        issues=len(attempts), issues_resolved_at_least_once=int(by_issue.resolved_attempts.gt(0).sum()),
        attempt_counts=stats(attempts),
        attempts_per_issue_frequency={int(k): int(v) for k, v in attempts.value_counts().items()},
        turns=stats(meta.turns), calls=stats(meta.calls), reconstructed_attempts=len(initial),
        reconstructed_assistant_inputs=len(turns), prompt_tokens=stats(turns.prompt),
        initial_prompt_tokens=stats(meta.first_tokens.dropna()),
        rendered_system_only_tokens=stats(meta.system_only_tokens.dropna()),
        rendered_system_and_tools_tokens=stats(meta.first_header_tokens.dropna()),
        token_increase_from_tool_template=stats((meta.first_header_tokens - meta.system_only_tokens).dropna()),
        final_prompt_tokens=stats(meta.last_tokens.dropna()),
        growth_by_program=stats(meta.growth.dropna()),
        shared_initial=sharing(meta, initial, samples),
        constructed_pairs=opportunities(meta, initial),
    )
    outcomes = meta.groupby(["status", "resolved"], dropna=False).size().reset_index(name="attempts")
    outcomes.to_csv(output / "outcomes.csv", index=False)
    turns["stage"] = pd.Categorical(
        meta.stage.to_numpy()[turns.row.to_numpy()], categories=BANDS, ordered=True
    )
    turns["phase"] = np.minimum(
        4, (turns.turn.to_numpy() - 1) * 4 // meta.turns.to_numpy()[turns.row.to_numpy()] + 1
    )
    adj = turns.loc[turns.lcp.ge(0)].copy()
    adj["ratio"] = adj.lcp / adj.prompt
    adj["nonshared"] = adj.prompt - adj.lcp
    summary["adjacent"] = {
        "lcp": stats(adj.lcp), "ratio": stats(adj.ratio), "nonshared": stats(adj.nonshared),
        "net_token_growth": stats(adj.growth), "new_messages": stats(adj.new_messages),
        "previous_calls": stats(adj.previous_calls),
        "common_fraction_token_weighted": float(adj.lcp.sum() / adj.prompt.sum()),
        "growth_nonpositive_count": int(adj.growth.le(0).sum()),
        "without_tool_call_n": int(adj.previous_calls.eq(0).sum()),
        "appended_token_mean_with_tool_call": float(adj.loc[adj.previous_calls.gt(0), "growth"].mean()),
        "appended_token_mean_without_tool_call": float(adj.loc[adj.previous_calls.eq(0), "growth"].mean()),
        "aligned": {str(b): {
            "tokens": stats((adj.lcp // b) * b),
            "lost_to_alignment": stats(adj.lcp % b),
        } for b in BLOCKS},
    }
    summary["relative_turn_quarters"] = {
        int(q): {"prompt": stats(g.prompt), "lcp": stats(g.lcp), "ratio": stats(g.ratio),
                 "nonshared": stats(g.nonshared)}
        for q, g in adj.groupby("phase")
    }
    metrics = ["turns", "calls", "first_tokens", "last_tokens", "growth",
               "last_lcp", "tool_result_chars", "tool_argument_chars"]
    call_metrics = [c for c in meta if c.startswith("calls_")]
    summary["by_resolved"] = {
        int(k): {c: stats(g[c].fillna(0) if c in call_metrics else g[c].dropna())
                 for c in metrics + call_metrics}
        for k, g in meta.loc[meta.resolved.isin([0, 1])].groupby("resolved")
    }
    summary["assistant_turns_by_resolved"] = {
        int(outcome): int(group.turns.sum())
        for outcome, group in meta.loc[meta.resolved.isin([0, 1])].groupby("resolved")
    }
    by_band = []
    for label in BANDS:
        g = meta.loc[meta.stage.eq(label)]
        a = adj.loc[adj.stage.eq(label)]
        observed = g.loc[g.resolved.isin([0, 1]), "resolved"]
        by_band.append({
            "turn_band": label, "attempts": len(g), "resolved": observed.sum(),
            "labelled_attempts": len(observed), "resolution_rate": observed.mean(),
            "initial_tokens_p50": g.first_tokens.median(), "last_tokens_p50": g.last_tokens.median(),
            "last_tokens_p90": g.last_tokens.quantile(.9), "growth_tokens_p50": g.growth.median(),
            "calls_p50": g.calls.median(), "adjacent_pairs": len(a), "lcp_p50": a.lcp.median(),
            "lcp_p90": a.lcp.quantile(.9), "reuse_p50": a.ratio.median(),
            "nonshared_p50": a.nonshared.median(),
        })
    pd.DataFrame(by_band).to_csv(output / "turn_bands.csv", index=False, float_format="%.6f")
    summary["same_band_outcomes"] = [
        {"band": label, "resolved": int(outcome), "attempts": len(g),
         "median_last_tokens": g.last_tokens.median(), "median_calls": g.calls.median()}
        for (label, outcome), g in meta.loc[meta.resolved.isin([0, 1])].groupby(["stage", "resolved"])
    ]
    per_ordinal = turns.groupby("turn").prompt.agg(
        attempts="size", prompt_p50="median", prompt_p90=lambda a: a.quantile(.9)
    ).join(adj.groupby("turn").agg(
        adjacent_pairs=("lcp", "size"), lcp_p50=("lcp", "median"),
        reuse_p50=("ratio", "median"), nonshared_p50=("nonshared", "median"),
        new_messages_p50=("new_messages", "median"), net_growth_p50=("growth", "median"),
    ))
    per_ordinal.to_csv(output / "turn_profile.csv", float_format="%.6f")
    plot(meta, turns, adj, pd.DataFrame(by_band), output)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n",
                                        encoding="utf-8")


def plot(meta, turns, adj, bands, output):
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    turn_counts = meta.turns.value_counts().sort_index()
    axes[0, 0].bar(turn_counts.index, turn_counts.values, color="#1b728b")
    axes[0, 0].set(xlabel="Observed assistant turns", ylabel="Attempts")
    for label, g in turns.groupby("stage", observed=True):
        g = g.groupby("turn").prompt
        middle = g.median()
        middle = middle.loc[g.size().ge(30)]
        axes[0, 1].plot(middle.index, middle.values / 1_000, label=label)
    axes[0, 1].legend(title="Total turns", ncols=2, fontsize=8)
    axes[0, 1].set(xlabel="Turn", ylabel="Median reconstructed prompt (k tokens)")
    groups = adj.groupby("turn").lcp
    quantiles = groups.quantile([.1, .5, .9]).unstack().loc[groups.size().ge(30)] / 1_000
    axes[1, 0].fill_between(quantiles.index, quantiles[.1], quantiles[.9],
                           color="#c4dee7", label="P10–P90")
    axes[1, 0].plot(quantiles.index, quantiles[.5], color="#1b728b", label="Median")
    axes[1, 0].legend()
    axes[1, 0].set(xlabel="Current turn", ylabel="Adjacent LCP (k tokens)")
    bands = bands.loc[bands.attempts.gt(0)]
    bars = axes[1, 1].bar(bands.turn_band, bands.resolution_rate, color="#bf623c")
    for bar, count in zip(bars, bands.attempts):
        axes[1, 1].annotate(f"{count:,}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            xytext=(0, 4), textcoords="offset points", ha="center", fontsize=8)
    axes[1, 1].set(xlabel="Total turns", ylabel="Fraction resolved", ylim=(0, 1))
    for axis in axes.flat:
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", alpha=.2)
        axis.set_axisbelow(True)
    fig.savefig(output / "workload.png", dpi=155)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parquet", type=Path)
    parser.add_argument("tokenizer_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pair-samples", type=int, default=20_000)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if min(args.pair_samples, args.workers) < 1:
        parser.error("--pair-samples and --workers must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    threads = min(8, max(1, (os.cpu_count() or 1) // args.workers))
    os.environ.setdefault("RAYON_NUM_THREADS", str(threads))
    data = combine(args.parquet, args.tokenizer_dir, args.workers)
    summarize(*data, args.pair_samples, args.output)


if __name__ == "__main__":
    main()
