from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.config import (
    DEFAULT_FALLBACK_RATES,
    DEFAULT_MODEL_RATES,
    BudgetConfig,
    ConfigError,
    ModelRates,
    Paths,
    PricingConfig,
    load_budget_config,
    load_pricing_config,
)


class ConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.paths = Paths(
            codex_home=root / ".codex",
            state_db=root / ".codex" / "state_5.sqlite",
            sessions_dir=root / ".codex" / "sessions",
            config_dir=root / ".config" / "codex-stats",
            config_file=root / ".config" / "codex-stats" / "config.toml",
            output_dir=root / ".cache" / "codex-stats",
            dashboard_file=root / ".cache" / "codex-stats" / "dashboard.html",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_load_pricing_defaults_when_missing(self) -> None:
        config = load_pricing_config(self.paths)
        self.assertIsNone(config.default_usd_per_1k_tokens)

    def test_load_pricing_reads_effective_values(self) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_file.write_text(
            """
[pricing]
default_usd_per_1k_tokens = 0.02

[pricing.model_usd_per_1k_tokens]
gpt-5.4 = 0.03

[pricing.source_usd_per_1k_tokens]
claude = 0.02
""".strip(),
            encoding="utf-8",
        )
        pricing = load_pricing_config(self.paths)
        self.assertEqual(pricing.default_usd_per_1k_tokens, 0.02)
        self.assertEqual(pricing.model_rates["gpt-5.4"], ModelRates.uniform(0.03))
        self.assertEqual(pricing.source_rates["claude"], 0.02)

    def test_unknown_display_section_is_ignored(self) -> None:
        # A [display] table used to be validated and rejected, so a stale one
        # could stop the whole tool from starting. It is now inert.
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_file.write_text(
            """
[pricing]
default_usd_per_1k_tokens = 0.02

[display]
color = "blue"
history_limit = 0
compare_days = -1
""".strip(),
            encoding="utf-8",
        )
        self.assertEqual(load_pricing_config(self.paths).default_usd_per_1k_tokens, 0.02)

    def test_model_rate_table_parses_per_component(self) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_file.write_text(
            """
[pricing.model_usd_per_1k_tokens.gpt-5.4]
input = 0.003
cached_read = 0.0003
cache_write = 0.0
output = 0.015
""".strip(),
            encoding="utf-8",
        )
        rates = load_pricing_config(self.paths).rates_for("codex", "gpt-5.4")
        self.assertEqual(
            rates[0],
            ModelRates(input_usd_per_1k=0.003, cached_read_usd_per_1k=0.0003, cache_write_usd_per_1k=0.0, output_usd_per_1k=0.015),
        )
        self.assertFalse(rates[1])

    def test_unknown_model_falls_back_and_is_flagged(self) -> None:
        pricing = PricingConfig(default_usd_per_1k_tokens=0.02)
        rates, unrated = pricing.rates_for("opencode", "some-alias-model")
        self.assertEqual(rates, ModelRates.uniform(0.02))
        self.assertTrue(unrated)
        known, unrated_known = pricing.rates_for("codex", "gpt-5.4")
        self.assertFalse(unrated_known)
        self.assertEqual(known.cached_read_usd_per_1k, 0.00025)

    def test_default_fallback_is_component_aware(self) -> None:
        pricing = PricingConfig()
        rates, unrated = pricing.rates_for("claude", "stealth")
        self.assertTrue(unrated)
        self.assertEqual(rates, DEFAULT_FALLBACK_RATES)
        self.assertLess(rates.cached_read_usd_per_1k, rates.input_usd_per_1k)
        self.assertLess(rates.input_usd_per_1k, rates.output_usd_per_1k)

    def test_published_rates_match_official_per_token_prices(self) -> None:
        # gpt-5.6-terra: $2.00 input / $0.20 cached / $2.50 write / $12.00 output per 1M.
        self.assertEqual(
            DEFAULT_MODEL_RATES["gpt-5.6-terra"],
            ModelRates(0.002, 0.0002, 0.0025, 0.012),
        )
        # gpt-5.5: $5.00 input / $0.50 cached / no cache write / $30.00 output per 1M.
        self.assertEqual(
            DEFAULT_MODEL_RATES["gpt-5.5"],
            ModelRates(0.005, 0.0005, 0.0, 0.030),
        )
        # claude-opus-4.6: $5.00 input / $0.50 read / $6.25 5m write / $25.00 output per 1M.
        self.assertEqual(
            DEFAULT_MODEL_RATES["claude-opus-4.6"],
            ModelRates(0.005, 0.0005, 0.00625, 0.025),
        )

    def test_provider_prefixed_model_resolves_to_base_rates(self) -> None:
        pricing = PricingConfig()
        for source, model in (
            ("hermes", "anthropic/claude-opus-4.6"),
            ("claude", "anthropic/claude-haiku-4.5"),
            ("codex", "gpt-5.6-terra"),
        ):
            rates, unrated = pricing.rates_for(source, model)
            self.assertFalse(unrated, f"{source}/{model} should resolve to published rates")
            self.assertEqual(rates, DEFAULT_MODEL_RATES[model.rsplit('/', 1)[-1]])

    def test_explicit_model_key_wins_over_prefix_stripping(self) -> None:
        pricing = PricingConfig(model_rates={"claude-opus-4.6": ModelRates.uniform(0.5)})
        rates, unrated = pricing.rates_for("hermes", "anthropic/claude-opus-4.6")
        self.assertEqual(rates, ModelRates.uniform(0.5))
        self.assertFalse(unrated)

    def test_source_rate_overrides_model_table(self) -> None:
        pricing = PricingConfig(
            default_usd_per_1k_tokens=0.01,
            source_rates={"claude": 0.02},
            model_rates={"gpt-5.4": ModelRates.uniform(0.03)},
        )
        rates, unrated = pricing.rates_for("claude", "gpt-5.4")
        self.assertEqual(rates, ModelRates.uniform(0.02))
        self.assertFalse(unrated)
        self.assertEqual(pricing.rates_for("codex", "gpt-5.4")[0], ModelRates.uniform(0.03))

    def test_source_rates_apply_and_fall_back(self) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_file.write_text(
            """
[pricing]
default_usd_per_1k_tokens = 0.01

[pricing.source_usd_per_1k_tokens]
claude = 0.05
""".strip(),
            encoding="utf-8",
        )
        pricing = load_pricing_config(self.paths)
        self.assertEqual(pricing.rates_for("claude", None), (ModelRates.uniform(0.05), False))
        self.assertEqual(pricing.rates_for("opencode", None)[0], ModelRates.uniform(0.01))
        self.assertTrue(pricing.rates_for("opencode", None)[1])

    def _write_config(self, text: str) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_file.write_text(text.strip(), encoding="utf-8")

    def test_budget_absent_by_default_and_absent_from_file(self) -> None:
        self.assertEqual(load_budget_config(self.paths), BudgetConfig())
        self._write_config("[pricing]\ndefault_usd_per_1k_tokens = 0.01")
        self.assertEqual(load_budget_config(self.paths), BudgetConfig())

    def test_budget_parses_a_limit_and_ratio(self) -> None:
        self._write_config("[budget]\nmonthly_limit_usd = 120.0\nwarn_at_ratio = 0.75")
        self.assertEqual(
            load_budget_config(self.paths),
            BudgetConfig(monthly_limit_usd=120.0, warn_at_ratio=0.75),
        )

    def test_budget_uses_default_warn_ratio_when_omitted(self) -> None:
        self._write_config("[budget]\nmonthly_limit_usd = 100.0")
        budget = load_budget_config(self.paths)
        self.assertEqual(budget.monthly_limit_usd, 100.0)
        self.assertEqual(budget.warn_at_ratio, 0.8)

    def test_budget_rejects_a_boolean_limit(self) -> None:
        # True float()s to 1.0, same silent-inflation trap as a pricing rate.
        self._write_config("[budget]\nmonthly_limit_usd = true")
        with self.assertRaises(ConfigError):
            load_budget_config(self.paths)

    def test_budget_rejects_nonpositive_or_out_of_range_values(self) -> None:
        self._write_config("[budget]\nmonthly_limit_usd = 0")
        with self.assertRaises(ConfigError):
            load_budget_config(self.paths)
        self._write_config("[budget]\nmonthly_limit_usd = 10.0\nwarn_at_ratio = 1.5")
        with self.assertRaises(ConfigError):
            load_budget_config(self.paths)


if __name__ == "__main__":
    unittest.main()
