from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    codex_home: Path
    state_db: Path
    sessions_dir: Path
    config_dir: Path
    config_file: Path

    @classmethod
    def discover(cls) -> "Paths":
        codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
        config_dir = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "codex-stats"
        return cls(
            codex_home=codex_home,
            state_db=codex_home / "state_5.sqlite",
            sessions_dir=codex_home / "sessions",
            config_dir=config_dir,
            config_file=config_dir / "config.toml",
        )


@dataclass(frozen=True)
class ModelRates:
    input_usd_per_1k: float
    cached_read_usd_per_1k: float
    cache_write_usd_per_1k: float
    output_usd_per_1k: float

    @classmethod
    def uniform(cls, rate: float) -> "ModelRates":
        return cls(rate, rate, rate, rate)

    def cost_for(self, split) -> float:
        return round(
            (
                split.fresh_input * self.input_usd_per_1k
                + split.cached_read * self.cached_read_usd_per_1k
                + split.cache_write * self.cache_write_usd_per_1k
                + split.output * self.output_usd_per_1k
            )
            / 1000.0,
            6,
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "input": self.input_usd_per_1k,
            "cached_read": self.cached_read_usd_per_1k,
            "cache_write": self.cache_write_usd_per_1k,
            "output": self.output_usd_per_1k,
        }


def _per_1m(
    input_usd: float,
    cached_read_usd: float,
    cache_write_usd: float,
    output_usd: float,
) -> ModelRates:
    """Convert published USD-per-million-token prices into the per-1k rates we store."""
    return ModelRates(
        input_usd_per_1k=input_usd / 1000.0,
        cached_read_usd_per_1k=cached_read_usd / 1000.0,
        cache_write_usd_per_1k=cache_write_usd / 1000.0,
        output_usd_per_1k=output_usd / 1000.0,
    )


RATE_SNAPSHOT_DATE = "2026-09-26"
RATE_SNAPSHOT_SOURCES = (
    "https://developers.openai.com/api/docs/pricing",
    "https://platform.claude.com/docs/en/about-claude/pricing",
)

# Published prices in USD per million tokens, as
# (input, cached input, cache write, output).
#
# OpenAI: standard processing, short context. OpenAI only bills explicit cache writes
# from GPT-5.6 onward; earlier models use implicit caching with no write charge, so
# their cache_write rate is 0. Long-context (>272k) rates are not modeled here.
_OPENAI_RATES_PER_1M: dict[str, tuple[float, float, float, float]] = {
    "gpt-5.6-sol": (4.00, 0.40, 5.00, 20.00),
    "gpt-5.6-terra": (2.00, 0.20, 2.50, 12.00),
    "gpt-5.6-luna": (0.20, 0.02, 0.25, 1.20),
    "gpt-5.5": (5.00, 0.50, 0.00, 30.00),
    "gpt-5.4": (2.50, 0.25, 0.00, 15.00),
    "gpt-5.4-mini": (0.75, 0.075, 0.00, 4.50),
    "gpt-5.4-nano": (0.20, 0.02, 0.00, 1.25),
    "gpt-5.3-codex": (1.75, 0.175, 0.00, 14.00),
    "gpt-5.2": (1.75, 0.175, 0.00, 14.00),
    "gpt-5.1": (1.25, 0.125, 0.00, 10.00),
    "gpt-5.1-codex-mini": (0.25, 0.025, 0.00, 2.00),
    "gpt-5": (1.25, 0.125, 0.00, 10.00),
    "gpt-5-mini": (0.25, 0.025, 0.00, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.00, 0.40),
    "gpt-4.1": (2.00, 0.50, 0.00, 8.00),
    "gpt-4o": (2.50, 1.25, 0.00, 10.00),
    "o3": (2.00, 0.50, 0.00, 8.00),
    "o4-mini": (1.10, 0.275, 0.00, 4.40),
}

# Anthropic: standard pricing with 5-minute cache writes. Transcripts do report a
# 1-hour write count (usage.cache_creation.ephemeral_1h_input_tokens) but it is 0 across
# every recorded session, so only the 5-minute rate is used; 1-hour writes would cost 2x
# base input instead of 1.25x. Batch (-50%), fast mode, and the 1.1x data-residency
# multiplier are not modeled.
_ANTHROPIC_RATES_PER_1M: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5.1": (10.00, 0.25, 12.50, 50.00),
    "claude-fable-5": (10.00, 1.00, 12.50, 50.00),
    "claude-opus-5.5": (4.00, 0.20, 5.00, 20.00),
    "claude-opus-5": (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4.8": (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4.7": (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4.6": (5.00, 0.50, 6.25, 25.00),
    "claude-opus-4.5": (5.00, 0.50, 6.25, 25.00),
    "claude-sonnet-5": (2.00, 0.20, 2.50, 10.00),
    "claude-sonnet-4.6": (3.00, 0.30, 3.75, 15.00),
    "claude-sonnet-4.5": (3.00, 0.30, 3.75, 15.00),
    "claude-haiku-4.5": (1.00, 0.10, 1.25, 5.00),
}

DEFAULT_MODEL_RATES: dict[str, ModelRates] = {
    **{name: _per_1m(*rates) for name, rates in _OPENAI_RATES_PER_1M.items()},
    **{name: _per_1m(*rates) for name, rates in _ANTHROPIC_RATES_PER_1M.items()},
}

# Mid-tier published rates (Claude Sonnet class) used only for models that cannot be
# identified, such as third-party aliases. This is a rough estimate, never a quote, and
# is always surfaced as a fallback rate in the dashboard.
DEFAULT_FALLBACK_RATES = _per_1m(3.00, 0.30, 3.75, 15.00)


@dataclass(frozen=True)
class PricingConfig:
    default_usd_per_1k_tokens: float | None = None
    model_rates: dict[str, ModelRates] | None = None
    source_rates: dict[str, float] | None = None

    def rates_for(self, source: str, model: str | None) -> tuple[ModelRates, bool]:
        if source and self.source_rates and source in self.source_rates:
            return ModelRates.uniform(self.source_rates[source]), False
        if model:
            for table in (self.model_rates, DEFAULT_MODEL_RATES):
                found = _lookup_rates(table, source, model)
                if found is not None:
                    return found, False
        if self.default_usd_per_1k_tokens is not None:
            return ModelRates.uniform(self.default_usd_per_1k_tokens), True
        return DEFAULT_FALLBACK_RATES, True


def _lookup_rates(table: dict[str, ModelRates] | None, source: str, model: str) -> ModelRates | None:
    if not table:
        return None
    for key in _rate_keys(source, model):
        if key in table:
            return table[key]
    return None


def _rate_keys(source: str, model: str) -> list[str]:
    """Candidate lookup keys, most specific first.

    Sources record the same model under different spellings: Codex writes bare
    ``gpt-5.6-terra`` while Hermes and Claude Code write ``anthropic/claude-opus-4.6``.
    An exact match always wins; stripping a provider prefix is only a fallback.
    """
    keys = [model]
    if source:
        keys.append(f"{source}/{model}")
    if "/" in model:
        bare = model.rsplit("/", 1)[-1]
        keys.append(bare)
        if source:
            keys.append(f"{source}/{bare}")
    return keys


@dataclass(frozen=True)
class DisplayConfig:
    color: str = "auto"
    history_limit: int = 10
    compare_days: int = 7


@dataclass(frozen=True)
class AppConfig:
    pricing: PricingConfig
    display: DisplayConfig


def load_config(paths: Paths) -> AppConfig:
    if not paths.config_file.exists():
        return AppConfig(pricing=PricingConfig(), display=DisplayConfig())

    payload = tomllib.loads(paths.config_file.read_text(encoding="utf-8"))
    pricing = payload.get("pricing", {})
    default_rate_raw = pricing.get("default_usd_per_1k_tokens")
    default_rate = float(default_rate_raw) if default_rate_raw is not None else None
    model_rates = _flatten_model_rates(pricing.get("model_usd_per_1k_tokens", {}))
    source_rates = {str(k): float(v) for k, v in pricing.get("source_usd_per_1k_tokens", {}).items()}
    display = payload.get("display", {})
    color = str(display.get("color", "auto"))
    if color not in {"auto", "always", "never"}:
        raise ValueError("display.color must be one of: auto, always, never")
    history_limit = int(display.get("history_limit", 10))
    compare_days = int(display.get("compare_days", 7))
    if history_limit <= 0:
        raise ValueError("display.history_limit must be greater than 0")
    if compare_days <= 0:
        raise ValueError("display.compare_days must be greater than 0")
    return AppConfig(
        pricing=PricingConfig(
            default_usd_per_1k_tokens=default_rate,
            model_rates=model_rates,
            source_rates=source_rates,
        ),
        display=DisplayConfig(color=color, history_limit=history_limit, compare_days=compare_days),
    )


def load_pricing_config(paths: Paths) -> PricingConfig:
    return load_config(paths).pricing


def _flatten_model_rates(payload: dict, prefix: str = "") -> dict[str, ModelRates]:
    flattened: dict[str, ModelRates] = {}
    for key, value in payload.items():
        next_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            rates = _parse_rate_table(value)
            if rates is None:
                flattened.update(_flatten_model_rates(value, next_key))
            else:
                flattened[next_key] = rates
        else:
            flattened[next_key] = ModelRates.uniform(float(value))
    return flattened


_RATE_FIELDS = {
    "input": "input_usd_per_1k",
    "input_tokens": "input_usd_per_1k",
    "cached_read": "cached_read_usd_per_1k",
    "cache_read": "cached_read_usd_per_1k",
    "cached_input": "cached_read_usd_per_1k",
    "cache_write": "cache_write_usd_per_1k",
    "cache_creation": "cache_write_usd_per_1k",
    "output": "output_usd_per_1k",
    "output_tokens": "output_usd_per_1k",
}


def _parse_rate_table(payload: dict) -> ModelRates | None:
    fields = {_RATE_FIELDS[k]: float(v) for k, v in payload.items() if k in _RATE_FIELDS}
    if not fields:
        return None
    return ModelRates(
        input_usd_per_1k=fields.get("input_usd_per_1k", 0.0),
        cached_read_usd_per_1k=fields.get("cached_read_usd_per_1k", 0.0),
        cache_write_usd_per_1k=fields.get("cache_write_usd_per_1k", 0.0),
        output_usd_per_1k=fields.get("output_usd_per_1k", 0.0),
    )
