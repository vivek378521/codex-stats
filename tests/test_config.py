from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.config import Paths, load_config


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
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_load_config_defaults_when_missing(self) -> None:
        config = load_config(self.paths)
        self.assertEqual(config.display.color, "auto")
        self.assertEqual(config.display.history_limit, 10)
        self.assertEqual(config.display.compare_days, 7)
        self.assertEqual(config.pricing.default_usd_per_1k_tokens, 0.01)

    def test_load_config_reads_effective_values(self) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_file.write_text(
            """
[pricing]
default_usd_per_1k_tokens = 0.02

[pricing.model_usd_per_1k_tokens]
gpt-5.4 = 0.03

[pricing.source_usd_per_1k_tokens]
claude = 0.02

[display]
color = "never"
history_limit = 20
compare_days = 14
""".strip(),
            encoding="utf-8",
        )
        app_config = load_config(self.paths)
        self.assertEqual(app_config.pricing.default_usd_per_1k_tokens, 0.02)
        self.assertEqual(app_config.pricing.model_rates["gpt-5.4"], 0.03)
        self.assertEqual(app_config.pricing.source_rates["claude"], 0.02)
        self.assertEqual(app_config.display.color, "never")
        self.assertEqual(app_config.display.history_limit, 20)
        self.assertEqual(app_config.display.compare_days, 14)

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
        pricing = load_config(self.paths).pricing
        self.assertEqual(pricing.rate_for_source("claude", None), 0.05)
        self.assertEqual(pricing.rate_for_source("opencode", None), 0.01)
        self.assertEqual(pricing.rate_for_model(None), 0.01)

    def test_invalid_display_config_raises(self) -> None:
        self.paths.config_dir.mkdir(parents=True, exist_ok=True)
        self.paths.config_file.write_text(
            """
[display]
color = "blue"
history_limit = 0
compare_days = 7
""".strip(),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            load_config(self.paths)


if __name__ == "__main__":
    unittest.main()
