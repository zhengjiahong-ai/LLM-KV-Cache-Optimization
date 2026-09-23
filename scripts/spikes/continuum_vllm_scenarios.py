"""Deterministic workload descriptions for the vLLM observation spike."""

from __future__ import annotations

from dataclasses import dataclass

SCENARIO_NAMES = (
    "environment_smoke",
    "request_lifecycle_cleanup",
    "same_prefix_cross_request_reuse",
    "namespace_isolation",
    "block_eviction_and_reassignment",
    "partial_prefix",
)


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str")
    if not value.strip():
        raise ValueError(f"{name} must be non-empty")
    return value


def _require_positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be int")
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class ScenarioSampling:
    """Sampling values shared by every request in one scenario."""

    max_tokens: int
    seed: int
    temperature: float

    def __post_init__(self) -> None:
        _require_positive_int(self.max_tokens, "max_tokens")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise TypeError("seed must be int")
        if not isinstance(self.temperature, (int, float)) or isinstance(
            self.temperature, bool
        ):
            raise TypeError("temperature must be numeric")
        if float(self.temperature) != 0.0:
            raise ValueError("formal scenarios require temperature=0.0")


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    """Explicit immutable inputs from which scenario requests are derived."""

    model: str
    model_revision: str
    tokenizer: str
    tokenizer_revision: str
    block_size: int
    pressure_request_count: int
    pressure_prompt_tokens: int
    max_tokens: int
    seed: int
    temperature: float

    def __post_init__(self) -> None:
        for field_name in (
            "model",
            "model_revision",
            "tokenizer",
            "tokenizer_revision",
        ):
            _require_text(getattr(self, field_name), field_name)
        for field_name in (
            "block_size",
            "pressure_request_count",
            "pressure_prompt_tokens",
            "max_tokens",
        ):
            _require_positive_int(getattr(self, field_name), field_name)
        ScenarioSampling(self.max_tokens, self.seed, self.temperature)


@dataclass(frozen=True, slots=True)
class ScenarioRequest:
    """One prompt and its external program identity."""

    program_id: str
    prompt: str
    cache_salt: str | None = None
    variant: str = "default"
    prefix_token_count: int | None = None
    suffix_text: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.program_id, "program_id")
        _require_text(self.prompt, "prompt")
        _require_text(self.variant, "variant")
        if self.cache_salt is not None:
            _require_text(self.cache_salt, "cache_salt")
        if self.prefix_token_count is not None:
            _require_positive_int(self.prefix_token_count, "prefix_token_count")
            if self.suffix_text is None:
                raise ValueError("token-prefix request requires suffix_text")
        if self.suffix_text is not None:
            _require_text(self.suffix_text, "suffix_text")
            if self.prefix_token_count is None:
                raise ValueError("suffix_text requires prefix_token_count")


@dataclass(frozen=True, slots=True)
class ScenarioPlan:
    """Complete deterministic request plan for a named scenario."""

    name: str
    requests: tuple[ScenarioRequest, ...]
    sampling: ScenarioSampling

    def __post_init__(self) -> None:
        if self.name not in SCENARIO_NAMES:
            raise ValueError(f"unknown scenario: {self.name}")
        if not isinstance(self.requests, tuple) or not self.requests:
            raise ValueError("requests must be a non-empty tuple")
        if not all(isinstance(item, ScenarioRequest) for item in self.requests):
            raise TypeError("requests must contain ScenarioRequest values")
        program_ids = [item.program_id for item in self.requests]
        if len(program_ids) != len(set(program_ids)):
            raise ValueError("program_id values must be unique within a scenario")
        if not isinstance(self.sampling, ScenarioSampling):
            raise TypeError("sampling must be ScenarioSampling")


def _shared_prefix(token_target: int) -> str:
    return " ".join(f"shared-{index:04d}" for index in range(token_target))


def build_scenario(name: str, config: ScenarioConfig) -> ScenarioPlan:
    """Build one of the six frozen workloads without importing vLLM."""

    if name not in SCENARIO_NAMES:
        raise ValueError(f"unknown scenario: {name}")
    if not isinstance(config, ScenarioConfig):
        raise TypeError("config must be ScenarioConfig")

    sampling = ScenarioSampling(config.max_tokens, config.seed, config.temperature)
    shared = _shared_prefix(max(config.block_size * 2, 32))

    if name == "environment_smoke":
        requests = (ScenarioRequest("program-smoke", "State one color."),)
    elif name == "request_lifecycle_cleanup":
        requests = (ScenarioRequest("program-lifecycle", f"{shared} lifecycle"),)
    elif name == "same_prefix_cross_request_reuse":
        requests = (
            ScenarioRequest("program-reuse-a", f"{shared} suffix-a"),
            ScenarioRequest("program-reuse-b", f"{shared} suffix-b"),
        )
    elif name == "namespace_isolation":
        prompt = f"{shared} namespace"
        requests = (
            ScenarioRequest("program-namespace-a", prompt, cache_salt="namespace-a"),
            ScenarioRequest("program-namespace-b", prompt, cache_salt="namespace-b"),
        )
    elif name == "block_eviction_and_reassignment":
        requests = tuple(
            ScenarioRequest(
                f"program-pressure-{index:04d}",
                " ".join(
                    f"pressure-{index:04d}-{token:04d}"
                    for token in range(config.pressure_prompt_tokens)
                ),
            )
            for index in range(config.pressure_request_count)
        )
    else:
        aligned = config.block_size * 2
        unaligned = aligned + 1
        requests = (
            ScenarioRequest(
                "program-partial-aligned-a",
                shared,
                variant="aligned-prefix-a",
                prefix_token_count=aligned,
                suffix_text="suffix-a",
            ),
            ScenarioRequest(
                "program-partial-aligned-b",
                shared,
                variant="aligned-prefix-b",
                prefix_token_count=aligned,
                suffix_text="suffix-b",
            ),
            ScenarioRequest(
                "program-partial-unaligned-a",
                shared,
                variant="unaligned-prefix-a",
                prefix_token_count=unaligned,
                suffix_text="suffix-a",
            ),
            ScenarioRequest(
                "program-partial-unaligned-b",
                shared,
                variant="unaligned-prefix-b",
                prefix_token_count=unaligned,
                suffix_text="suffix-b",
            ),
        )

    return ScenarioPlan(name=name, requests=requests, sampling=sampling)


def materialize_prompts(
    plan: ScenarioPlan,
    tokenizer: object | None,
) -> tuple[dict[str, object], ...]:
    """Create vLLM prompt dictionaries, using token IDs for exact boundaries."""

    prompts: list[dict[str, object]] = []
    for request in plan.requests:
        if request.prefix_token_count is None:
            prompt: dict[str, object] = {"prompt": request.prompt}
        else:
            if tokenizer is None:
                raise ValueError("partial-prefix materialization requires tokenizer")
            encoded = tokenizer.encode(  # type: ignore[attr-defined]
                request.prompt,
                add_special_tokens=False,
            )
            if len(encoded) < request.prefix_token_count:
                raise ValueError("token source is shorter than requested shared prefix")
            suffix = tokenizer.encode(  # type: ignore[attr-defined]
                request.suffix_text,
                add_special_tokens=False,
            )
            if not suffix:
                raise ValueError("tokenized suffix must not be empty")
            prompt = {
                "prompt_token_ids": [
                    *encoded[: request.prefix_token_count],
                    *suffix,
                ]
            }
        if request.cache_salt is not None:
            prompt["cache_salt"] = request.cache_salt
        prompts.append(prompt)
    return tuple(prompts)
