from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .models import ConfigView, DisplayConfigView


DEFAULT_CONFIG_TEXT = """[pricing]
default_usd_per_1k_tokens = 0.01

[pricing.model_usd_per_1k_tokens]
# gpt-5.4 = 0.02
# gpt-5-mini = 0.005

[display]
color = "auto"
history_limit = 10
compare_days = 7
"""


@dataclass(frozen=True)
class Paths:
    codex_home: Path
    state_db: Path
    logs_db: Path
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
            logs_db=codex_home / "logs_1.sqlite",
            sessions_dir=codex_home / "sessions",
            config_dir=config_dir,
            config_file=config_dir / "config.toml",
        )


@dataclass(frozen=True)
class PricingConfig:
    default_usd_per_1k_tokens: float = 0.01
    model_rates: dict[str, float] | None = None

    def rate_for_model(self, model: str | None) -> float:
        if model and self.model_rates and model in self.model_rates:
            return self.model_rates[model]
        return self.default_usd_per_1k_tokens


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
        pricing=PricingConfig(default_usd_per_1k_tokens=default_rate, model_rates=model_rates),
        display=DisplayConfig(color=color, history_limit=history_limit, compare_days=compare_days),
    )


def load_pricing_config(paths: Paths) -> PricingConfig:
    return load_config(paths).pricing


def load_display_config(paths: Paths) -> DisplayConfig:
    return load_config(paths).display


def load_config_view(paths: Paths) -> ConfigView:
    app_config = load_config(paths)
    return ConfigView(
        config_path=str(paths.config_file),
        exists=paths.config_file.exists(),
        pricing_default_usd_per_1k_tokens=app_config.pricing.default_usd_per_1k_tokens,
        pricing_model_overrides=app_config.pricing.model_rates or {},
        display=DisplayConfigView(
            color=app_config.display.color,
            history_limit=app_config.display.history_limit,
            compare_days=app_config.display.compare_days,
        ),
    )


def _flatten_model_rates(payload: dict, prefix: str = "") -> dict[str, float]:
    flattened: dict[str, float] = {}
    for key, value in payload.items():
        next_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten_model_rates(value, next_key))
        else:
            flattened[next_key] = float(value)
    return flattened


def init_config(paths: Paths, force: bool = False) -> Path:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    if paths.config_file.exists() and not force:
        return paths.config_file
    paths.config_file.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return paths.config_file
