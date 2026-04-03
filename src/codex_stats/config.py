from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


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


def load_pricing_config(paths: Paths) -> PricingConfig:
    if not paths.config_file.exists():
        return PricingConfig()

    payload = tomllib.loads(paths.config_file.read_text(encoding="utf-8"))
    pricing = payload.get("pricing", {})
    default_rate = float(pricing.get("default_usd_per_1k_tokens", 0.01))
    model_rates = {
        str(model): float(rate)
        for model, rate in pricing.get("model_usd_per_1k_tokens", {}).items()
    }
    return PricingConfig(default_usd_per_1k_tokens=default_rate, model_rates=model_rates)
