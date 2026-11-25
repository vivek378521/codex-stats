from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import build_parser, main
from codex_stats.config import Paths
from codex_stats.display import format_dashboard_html
from codex_stats.models import DashboardData
from codex_stats.sources import (
    SOURCE_CLAUDE,
    SOURCE_CODEX,
    SOURCE_DSH,
    SOURCE_HERMES,
    SOURCE_OPENCODE,
)
from codex_stats.telemetry import (
    DISCLAIMER,
    OFF,
    ON,
    PROFILES,
    TelemetryReport,
    build_telemetry_report,
    write_telemetry_report,
)


def _paths(root: Path) -> Paths:
    return Paths(
        codex_home=root / "codex",
        state_db=root / "codex" / "state_5.sqlite",
        sessions_dir=root / "codex" / "sessions",
        config_dir=root / "config",
        config_file=root / "config" / "config.toml",
        output_dir=root / "cache",
        dashboard_file=root / "cache" / "dashboard.html",
    )


def _setting(report: TelemetryReport, key: str, name: str):
    harness = next(item for item in report.harnesses if item.profile.key == key)
    return next(setting for setting in harness.settings if setting.name == name)


class TelemetryCatalogTestCase(unittest.TestCase):
    def test_all_supported_harnesses_have_cited_profiles(self) -> None:
        self.assertEqual(
            {profile.key for profile in PROFILES},
            {SOURCE_CODEX, SOURCE_OPENCODE, SOURCE_CLAUDE, SOURCE_HERMES, SOURCE_DSH},
        )
        for profile in PROFILES:
            self.assertTrue(profile.evidence)
            self.assertTrue(all(item.url.startswith("https://") for item in profile.evidence))
            self.assertTrue(profile.opt_out)
            self.assertTrue(profile.summary)
            self.assertTrue(profile.opt_out_short)
            self.assertTrue(profile.destinations)
            self.assertTrue(profile.categories)

    def test_markdown_and_json_include_disclaimer_and_sources(self) -> None:
        report = TelemetryReport(generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc))
        markdown = report.to_markdown()
        self.assertIn(DISCLAIMER, markdown)
        self.assertIn("does not upload this report", DISCLAIMER)
        payload = json.loads(report.to_json())
        self.assertEqual(payload["reviewed_on"], "2026-11-25")
        self.assertEqual(payload["harnesses"], [])


class TelemetryDetectionTestCase(unittest.TestCase):
    def test_codex_reads_analytics_and_prompt_logging_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            paths.codex_home.mkdir(parents=True)
            (paths.codex_home / "config.toml").write_text(
                "[analytics]\nenabled = false\n[otel]\nlog_user_prompt = true\n",
                encoding="utf-8",
            )
            report = build_telemetry_report(paths)
            self.assertEqual(_setting(report, SOURCE_CODEX, "analytics.enabled").state, OFF)
            self.assertEqual(_setting(report, SOURCE_CODEX, "otel.log_user_prompt").state, ON)
            harness = next(item for item in report.harnesses if item.profile.key == SOURCE_CODEX)
            self.assertIn("analytics off", harness.local_summary)

    def test_claude_env_flags_and_queued_events_are_reported_without_identifiers(self) -> None:
        secret_device_id = "f7dfb065c1ecea99e69afbfe09967d1dcda2029d6159534072b8cc970b8847f8"
        event = json.dumps(
            {
                "event_type": "ClaudeCodeInternalEvent",
                "event_data": {
                    "event_name": "tengu_config_cache_stats",
                    "device_id": secret_device_id,
                    "session_id": "session-123",
                    "model": "claude-opus-4-8",
                    "additional_metadata": "eyJjYWNoZV9oaXRzIjo0NTY4Nn0=",
                },
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude = root / "claude"
            telemetry = claude / "telemetry"
            telemetry.mkdir(parents=True)
            (telemetry / "failed.json").write_text(event + "\n", encoding="utf-8")
            env = {
                "CLAUDE_CONFIG_DIR": str(claude),
                "DISABLE_TELEMETRY": "1",
                "DISABLE_ERROR_REPORTING": "1",
                "DISABLE_FEEDBACK_COMMAND": "1",
            }
            with mock.patch.dict(os.environ, env, clear=True):
                report = build_telemetry_report(_paths(root))
            harness = next(item for item in report.harnesses if item.profile.key == SOURCE_CLAUDE)
            self.assertEqual(_setting(report, SOURCE_CLAUDE, "DISABLE_TELEMETRY").state, ON)
            self.assertIn("disabled", harness.local_summary)
            rendered = report.to_json() + report.to_markdown()
            self.assertIn("tengu_config_cache_stats", rendered)
            self.assertIn("cache_hits", rendered)
            self.assertNotIn(secret_device_id, rendered)
            self.assertNotIn("session-123", rendered)

    def test_opencode_strips_json_comments_and_reads_share_setting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config" / "opencode"
            config_dir.mkdir(parents=True)
            (config_dir / "opencode.jsonc").write_text(
                '{\n // comment\n "$schema": "https://opencode.ai/config.json",\n "share": "disabled",\n "autoupdate": false\n}\n',
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config")}, clear=True):
                report = build_telemetry_report(_paths(root))
            self.assertEqual(_setting(report, SOURCE_OPENCODE, "share").value, "disabled")
            self.assertEqual(_setting(report, SOURCE_OPENCODE, "share").state, OFF)
            self.assertEqual(_setting(report, SOURCE_OPENCODE, "autoupdate").state, OFF)

    def test_hermes_reads_nested_yaml_flags_without_yaml_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "hermes"
            home.mkdir(parents=True)
            (home / "config.yaml").write_text(
                "# comment\ntelemetry:\n  shared_metrics:\n    enabled: true\n    send: false\nupdates:\n  check: false\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(home)}, clear=True):
                report = build_telemetry_report(_paths(root))
            self.assertEqual(_setting(report, SOURCE_HERMES, "telemetry.shared_metrics.enabled").state, ON)
            self.assertEqual(_setting(report, SOURCE_HERMES, "telemetry.shared_metrics.send").state, OFF)
            harness = next(item for item in report.harnesses if item.profile.key == SOURCE_HERMES)
            self.assertIn("upload off", harness.local_summary)

    def test_dsh_env_disable_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"DSH_TELEMETRY_DISABLED": "1"}, clear=True):
                report = build_telemetry_report(_paths(Path(tmp)))
            self.assertEqual(_setting(report, SOURCE_DSH, "DSH_TELEMETRY_DISABLED").state, ON)
            harness = next(item for item in report.harnesses if item.profile.key == SOURCE_DSH)
            self.assertIn("disabled", harness.local_summary)


class TelemetryDisplayTestCase(unittest.TestCase):
    def test_dashboard_embeds_panel_and_download_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = build_telemetry_report(_paths(Path(tmp)))
            dashboard = DashboardData(
                generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
                telemetry=report,
            )
            html = format_dashboard_html(dashboard)
            self.assertIn("Telemetry and privacy", html)
            self.assertIn("the short version, per harness", html)
            self.assertIn("Anonymous usage and health metrics", html)
            self.assertIn("download-telemetry-json", html)
            self.assertIn("download-telemetry-md", html)
            self.assertIn("telemetryJson =", html)
            self.assertIn("telemetryMarkdown =", html)
            self.assertEqual(html.count("<script"), html.count("</script>"))

    def test_dashboard_without_report_has_no_panel(self) -> None:
        html = format_dashboard_html(DashboardData(generated_at=datetime(2026, 11, 25, tzinfo=timezone.utc)))
        self.assertNotIn("Telemetry and privacy", html)
        self.assertNotIn("Download JSON report", html)

    def test_cli_telemetry_report_writes_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            stdout = io.StringIO()
            with mock.patch("codex_stats.cli.Paths.discover", return_value=paths), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["--telemetry-report"]), 0)
            output = stdout.getvalue()
            self.assertIn("Nothing was uploaded", output)
            json_path, markdown_path = write_telemetry_report(
                build_telemetry_report(paths), paths.output_dir
            )
            self.assertTrue(json_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertIn("--telemetry-report", build_parser().format_help())


if __name__ == "__main__":
    unittest.main()
