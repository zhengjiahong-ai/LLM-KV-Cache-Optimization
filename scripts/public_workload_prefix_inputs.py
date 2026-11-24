"""Choose Issue clusters and reconstruct two pinned public chat projections."""
from hashlib import sha256
import json

from jinja2.sandbox import ImmutableSandboxedEnvironment
import pyarrow.parquet as pq
from tokenizers import Tokenizer

from analyze_nebius_openhands import GEN, MARK, Reconstruction, remove_arrow_nulls


class TargetTemplate(Reconstruction):
    """Apply the Qwen2.5 template to the same structured OpenHands messages."""

    def __init__(self, directory):
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        source = json.loads((directory / "tokenizer_config.json").read_bytes())["chat_template"]
        anchor = "{%- for message in messages %}"
        if source.count(anchor) != 1:
            raise ValueError("Expected pinned Qwen2.5 template")
        env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
        env.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)
        self.template = env.from_string(source)
        self.marked = env.from_string(source.replace(
            anchor, anchor + "{%- if message.role == 'assistant' %}{{ marker }}{%- endif %}"
        ))
        self.generation = self.encode(GEN)


def key(value):
    return sha256(("public-workload-v1/" + value).encode()).digest()


def select(frame, count):
    """Use identities only. Primary and comparison Issue sets are disjoint."""
    attempts = {}
    repos = {}
    for issue, records in frame.groupby("issue", sort=False):
        attempts[issue] = sorted(records.attempt, key=key)
        repos[issue] = records.repo.iloc[0]
    ordered = sorted(attempts, key=key)
    primary = [issue for issue in ordered if len(attempts[issue]) >= 2][:count]
    available = set(ordered) - set(primary)
    groups = []
    for i, issue in enumerate(primary):
        same_repo = i % 2 == 0
        partner = next((p for p in ordered
                        if p in available and (repos[p] == repos[issue]) == same_repo), None)
        if partner is None and same_repo:
            partner = next((p for p in ordered if p in available and repos[p] != repos[issue]), None)
        if partner is None:
            raise ValueError("Insufficient distinct Issue clusters")
        available.remove(partner)
        groups.append((f"G{i + 1:03}", issue, partner, repos[issue] == repos[partner],
                       *attempts[issue][:2], attempts[partner][0]))
    if len(groups) != count:
        raise ValueError("Insufficient issues with repeat attempts")
    return groups


def normalize(record, stop):
    raw, messages, positions = [], [], []
    for message in record["trajectory"]:
        if message["role"] == "assistant":
            if len(positions) == stop:
                break
            positions.append(len(messages))
        if message["role"] not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Unknown message role")
        raw.append(message)
        calls = []
        for call in message["tool_calls"] or []:
            arguments = json.loads(call["function"]["arguments"])
            if not isinstance(arguments, dict) or not call["function"]["name"]:
                raise ValueError("Invalid tool call")
            calls.append({"function": {"name": call["function"]["name"], "arguments": arguments}})
        messages.append({"role": message["role"], "content": message["content"] or "",
                         "tool_calls": calls})
    if not positions or positions[0] < 2 or messages[0]["role"] != "system":
        raise ValueError("Observed request lacks expected initial history")
    return raw, messages, positions


def common(left, right):
    for i, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return i
    return min(len(left), len(right))


def extract(projection, messages, positions, tools, warm, horizon, verify):
    segments = projection.messages(messages, tools)
    if len(segments) != len(positions) or not all(
        text.startswith("<|im_start|>assistant") for text in segments[1:]
    ):
        raise ValueError("Unexpected segmentation")
    encoded = projection.tokenizer.encode_batch_fast(segments, add_special_tokens=False)
    prefix, texts, prompts = [], [], {}
    delta = prior = None
    for k, (text, tokens) in enumerate(zip(segments, encoded, strict=True), 1):
        prefix.extend(tokens.ids)
        texts.append(text)
        if k == warm - 1:
            prior = tuple(prefix + projection.generation)
        if k == 1 or warm <= k <= warm + horizon:
            ids = tuple(prefix + projection.generation)
            rendered = "".join(texts) + GEN if verify or k == 1 else None
            prompts[k] = (rendered if k == 1 else None, ids)
            if verify:
                direct = projection.template.render(messages=messages[:positions[k-1]],
                                                      tools=tools, add_generation_prompt=True)
                if direct != rendered or tuple(projection.encode(direct)) != ids:
                    raise ValueError("Segmented and direct inputs differ")
            if k == warm:
                delta = (len(ids)-len(prior), common(prior, ids))
    return prompts, delta


def materialize(parquet, ids, source_dir, target_dir, warm, horizon):
    projections = {"qwen3": Reconstruction(source_dir), "qwen25": TargetTemplate(target_dir)}
    collected = {}
    file = pq.ParquetFile(parquet)
    for group in range(file.num_row_groups):
        identity = file.read_row_group(group, columns=["trajectory_id"]).column(0).to_pylist()
        indices = [i for i, value in enumerate(identity) if value in ids]
        if not indices:
            continue
        raw = file.read_row_group(group, columns=["trajectory", "tools", "trajectory_id"])
        for item in raw.take(indices).to_pylist():
            messages_raw, messages, positions = normalize(item, warm+horizon)
            tools = remove_arrow_nulls(item["tools"])
            if not tools:
                raise ValueError("Missing tool definitions")
            verify = len(collected) % 97 == 0
            streams, adjacent = {}, {}
            for name, projection in projections.items():
                streams[name], adjacent[name] = extract(
                    projection, messages, positions, tools, warm, horizon, verify
                )
            start = json.dumps(item["tools"], ensure_ascii=False) + "\n" + "\n".join(
                json.dumps(m, ensure_ascii=False) for m in messages_raw[:positions[0]]
            ) + "\n"
            collected[item["trajectory_id"]] = (start, streams, adjacent, verify)
        print(f"Reconstructed {len(collected)}/{len(ids)} attempts", flush=True)
    if set(collected) != ids:
        raise ValueError("Selected attempt identities missing from Parquet")
    return collected
