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


RATE_SNAPSHOT_DATE = "2026-09-26"

DEFAULT_MODEL_RATES: dict[str, ModelRates] = {
    "gpt-5.5": ModelRates(0.003, 0.0003, 0.0, 0.015),
    "gpt-5.4": ModelRates(0.003, 0.0003, 0.0, 0.015),
    "gpt-5.1-codex-mini": ModelRates(0.0008, 0.00008, 0.0, 0.004),
}

DEFAULT_FALLBACK_RATES = ModelRates(0.003, 0.0003, 0.003, 0.015)


@dataclass(frozen=True)
class PricingConfig:
    default_usd_per_1k_tokens: float = 0.01
    model_rates: dict[str, ModelRates] | None = None
    source_rates: dict[str, float] | None = None

    def rates_for(self, source: str, model: str | None) -> tuple[ModelRates, bool]:
        if source and self.source_rates and source in self.source_rates:
            return ModelRates.uniform(self.source_rates[source]), False
        if model and self.model_rates:
            if model in self.model_rates:
                return self.model_rates[model], False
            if f"{source}/{model}" in self.model_rates:
                return self.model_rates[f"{source}/{model}"], False
        if model and DEFAULT_MODEL_RATES.get(model):
            return DEFAULT_MODEL_RATES[model], False
        return ModelRates.uniform(self.default_usd_per_1k_tokens), True


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
    default_rate = float(pricing.get("default_usd_per_1k_tokens", 0.01))
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
