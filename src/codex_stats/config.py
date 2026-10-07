from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    codex_home: Path
    state_db: Path
    sessions_dir: Path
    config_dir: Path
    config_file: Path
    output_dir: Path
    dashboard_file: Path

    @classmethod
    def discover(cls) -> "Paths":
        codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
        config_dir = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "codex-stats"
        # A fixed path, not a fresh temp file per run. The dashboard is a page people
        # come back to, so it has to be reopenable and refreshable in place; a new
        # random filename each launch made yesterday's bookmark show stale numbers
        # with no way to tell, and left an orphan in the temp directory every time.
        output_dir = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "codex-stats"
        return cls(
            codex_home=codex_home,
            state_db=codex_home / "state_5.sqlite",
            sessions_dir=codex_home / "sessions",
            config_dir=config_dir,
            config_file=config_dir / "config.toml",
            output_dir=output_dir,
            dashboard_file=output_dir / "dashboard.html",
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
    _rates_cache: dict[tuple[str, str], tuple[ModelRates, bool]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def rates_for(self, source: str, model: str | None) -> tuple[ModelRates, bool]:
        key = (source or "", model or "")
        cached = self._rates_cache.get(key)
        if cached is not None:
            return cached
        if source and self.source_rates and source in self.source_rates:
            resolved = (ModelRates.uniform(self.source_rates[source]), False)
        elif model:
            found = None
            for table in (self.model_rates, DEFAULT_MODEL_RATES):
                found = _lookup_rates(table, source, model)
                if found is not None:
                    break
            if found is not None:
                resolved = (found, False)
            elif self.default_usd_per_1k_tokens is not None:
                resolved = (ModelRates.uniform(self.default_usd_per_1k_tokens), True)
            else:
                resolved = (DEFAULT_FALLBACK_RATES, True)
        elif self.default_usd_per_1k_tokens is not None:
            resolved = (ModelRates.uniform(self.default_usd_per_1k_tokens), True)
        else:
            resolved = (DEFAULT_FALLBACK_RATES, True)
        self._rates_cache[key] = resolved
        return resolved


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


class ConfigError(Exception):
    """The user's config file exists but could not be used.

    Raised as a message rather than left to propagate, because this file is written
    by hand from the README and a stray bracket is the most likely mistake anyone
    makes with it. A traceback out of a tool you run to look at a chart is a worse
    answer than a sentence naming the line and the file.
    """

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


@dataclass(frozen=True)
class BudgetConfig:
    """An optional monthly spend limit the dashboard compares itself against.

    Both fields come from ``[budget]`` in the same config.toml as pricing, so a
    budget is a number the user chose rather than the 30-day projection already on
    the page. ``warn_at_ratio`` is the fraction of the limit where the banner
    starts to look urgent; the default keeps a heads-up at 80%.
    """

    monthly_limit_usd: float | None = None
    warn_at_ratio: float = 0.8


def load_budget_config(paths: Paths) -> BudgetConfig:
    if not paths.config_file.exists():
        return BudgetConfig()
    raw = paths.config_file.read_text(encoding="utf-8")
    try:
        payload = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(paths.config_file, str(error)) from error
    if not isinstance(payload, dict):  # pragma: no cover - tomllib always returns a dict
        raise ConfigError(paths.config_file, "the file did not contain a table.")
    budget = payload.get("budget", {})
    if not isinstance(budget, dict):
        raise ConfigError(
            paths.config_file,
            "[budget] must be a table, so it needs to start with [budget] on its own line.",
        )
    limit_raw = budget.get("monthly_limit_usd")
    if limit_raw is None:
        return BudgetConfig()
    try:
        limit = _rate_number(limit_raw)
        ratio_raw = budget.get("warn_at_ratio", 0.8)
        ratio = _rate_number(ratio_raw) if ratio_raw is not None else 0.8
    except (TypeError, ValueError) as error:
        raise ConfigError(
            paths.config_file,
            f"{error}. Budget values must be numbers, for example monthly_limit_usd = 100.0.",
        ) from error
    if limit <= 0:
        raise ConfigError(paths.config_file, "monthly_limit_usd must be greater than zero.")
    if not 0 < ratio <= 1:
        raise ConfigError(paths.config_file, "warn_at_ratio must be between 0 and 1.")
    return BudgetConfig(monthly_limit_usd=limit, warn_at_ratio=ratio)


def load_pricing_config(paths: Paths) -> PricingConfig:
    if not paths.config_file.exists():
        return PricingConfig()

    raw = paths.config_file.read_text(encoding="utf-8")
    try:
        payload = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as error:
        # The parser knows the exact line and column, which is the difference between
        # a fixable sentence and a stack trace pointing into the standard library.
        raise ConfigError(paths.config_file, str(error)) from error
    if not isinstance(payload, dict):  # pragma: no cover - tomllib always returns a dict
        raise ConfigError(paths.config_file, "the file did not contain a table.")
    pricing = payload.get("pricing", {})
    if not isinstance(pricing, dict):
        raise ConfigError(
            paths.config_file,
            "[pricing] must be a table, so it needs to start with [pricing] on its own line.",
        )
    try:
        default_rate_raw = pricing.get("default_usd_per_1k_tokens")
        default_rate = _rate_number(default_rate_raw) if default_rate_raw is not None else None
        model_rates = _flatten_model_rates(pricing.get("model_usd_per_1k_tokens", {}))
        source_rates = {
            str(k): _rate_number(v) for k, v in pricing.get("source_usd_per_1k_tokens", {}).items()
        }
    except (TypeError, ValueError) as error:
        # A quoted rate, a boolean, or a word where a number belongs. Same class of
        # mistake as the syntax error above and the same fix: name the file and the
        # value instead of raising out of the middle of a float conversion.
        raise ConfigError(
            paths.config_file,
            f"{error}. Rates must be numbers, for example input = 0.0025.",
        ) from error
    return PricingConfig(
        default_usd_per_1k_tokens=default_rate,
        model_rates=model_rates,
        source_rates=source_rates,
    )


def _rate_number(value: object) -> float:
    """Coerce a configured rate, refusing values TOML can produce but nobody means.

    ``float()`` accepts a bool as 1.0, so ``default_usd_per_1k_tokens = true``
    would silently become a flat $1.00 per 1k tokens and inflate every cost on the
    page by roughly two orders of magnitude, with nothing on screen to say so. A
    quoted number is refused for the same reason: TOML already has a number type,
    and quotes are almost always a typo rather than an intent.
    """
    if isinstance(value, bool):
        raise ValueError(
            f"got the boolean {str(value).lower()}, which would be read as the rate {float(value)}."
        )
    if isinstance(value, str):
        raise ValueError(f"got the quoted string {value!r}; rates are written unquoted, as in 0.003.")
    return float(value)


def _flatten_model_rates(payload: dict, prefix: str = "") -> dict[str, ModelRates]:
    flattened: dict[str, ModelRates] = {}
    if not isinstance(payload, dict):
        raise ValueError(
            f"model_usd_per_1k_tokens must be a table, but it is a {type(payload).__name__}."
        )
    for key, value in payload.items():
        next_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            rates = _parse_rate_table(value)
            if rates is None:
                flattened.update(_flatten_model_rates(value, next_key))
            else:
                flattened[next_key] = rates
        else:
            flattened[next_key] = ModelRates.uniform(_rate_number(value))
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
    fields = {_RATE_FIELDS[k]: _rate_number(v) for k, v in payload.items() if k in _RATE_FIELDS}
    if not fields:
        return None
    return ModelRates(
        input_usd_per_1k=fields.get("input_usd_per_1k", 0.0),
        cached_read_usd_per_1k=fields.get("cached_read_usd_per_1k", 0.0),
        cache_write_usd_per_1k=fields.get("cache_write_usd_per_1k", 0.0),
        output_usd_per_1k=fields.get("output_usd_per_1k", 0.0),
    )
