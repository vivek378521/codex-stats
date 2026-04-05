from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import _open_report_in_browser, _write_report_output, build_parser


class CliTestCase(unittest.TestCase):
    def test_default_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.command)
        self.assertFalse(args.json_output)

    def test_session_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "--id", "abc"])
        self.assertEqual(args.command, "session")
        self.assertEqual(args.session_id, "abc")

    def test_models_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["models", "--json"])
        self.assertEqual(args.command, "models")
        self.assertTrue(args.json_output)

    def test_history_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["history", "--limit", "5"])
        self.assertEqual(args.command, "history")
        self.assertEqual(args.limit, 5)

    def test_costs_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["costs"])
        self.assertEqual(args.command, "costs")

    def test_insights_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["insights", "--json"])
        self.assertEqual(args.command, "insights")
        self.assertTrue(args.json_output)

    def test_global_days_and_color(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--days", "14", "--color", "never"])
        self.assertEqual(args.days, 14)
        self.assertEqual(args.color, "never")

    def test_global_color_default_is_deferred(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.color)

    def test_export_import_parsers(self) -> None:
        parser = build_parser()
        export_args = parser.parse_args(["export", "stats.json", "--since", "30d"])
        import_args = parser.parse_args(["import", "stats.json", "--json"])
        otel_args = parser.parse_args(
            [
                "otel",
                "--output",
                "metrics.json",
                "--endpoint",
                "http://localhost:4318/v1/metrics",
                "--since",
                "30d",
                "--daily-days",
                "14",
                "--resource-attr",
                "deployment.environment=dev",
                "--header",
                "Authorization=Bearer test",
                "--gzip",
            ]
        )
        self.assertEqual(export_args.command, "export")
        self.assertEqual(export_args.output, "stats.json")
        self.assertEqual(export_args.since, "30d")
        self.assertEqual(import_args.command, "import")
        self.assertTrue(import_args.json_output)
        self.assertEqual(otel_args.command, "otel")
        self.assertEqual(otel_args.output, "metrics.json")
        self.assertEqual(otel_args.endpoint, "http://localhost:4318/v1/metrics")
        self.assertEqual(otel_args.daily_days, 14)
        self.assertEqual(otel_args.resource_attr, ["deployment.environment=dev"])
        self.assertEqual(otel_args.header, ["Authorization=Bearer test"])
        self.assertTrue(otel_args.gzip)

    def test_daily_compare_doctor_parsers(self) -> None:
        parser = build_parser()
        daily_args = parser.parse_args(["daily", "--days", "14"])
        compare_args = parser.parse_args(["compare", "--days", "14", "--json"])
        doctor_args = parser.parse_args(["doctor", "--strict"])
        watch_args = parser.parse_args(
            [
                "watch",
                "--days",
                "14",
                "--interval",
                "2",
                "--project",
                "project",
                "--alert-cost-usd",
                "10",
                "--alert-tokens",
                "1000",
                "--alert-requests",
                "5",
                "--alert-delta-pct",
                "50",
                "--reset-state",
                "--once",
            ]
        )
        self.assertEqual(daily_args.command, "daily")
        self.assertEqual(daily_args.days, 14)
        self.assertEqual(compare_args.command, "compare")
        self.assertTrue(compare_args.json_output)
        self.assertEqual(doctor_args.command, "doctor")
        self.assertTrue(doctor_args.strict)
        self.assertEqual(watch_args.command, "watch")
        self.assertEqual(watch_args.interval, 2)
        self.assertEqual(watch_args.project_name, "project")
        self.assertEqual(watch_args.alert_cost_usd, 10)
        self.assertEqual(watch_args.alert_tokens, 1000)
        self.assertEqual(watch_args.alert_requests, 5)
        self.assertEqual(watch_args.alert_delta_pct, 50)
        self.assertTrue(watch_args.reset_state)
        self.assertTrue(watch_args.once)

    def test_compare_and_history_defaults_are_deferred(self) -> None:
        parser = build_parser()
        compare_args = parser.parse_args(["compare"])
        history_args = parser.parse_args(["history"])
        self.assertIsNone(compare_args.days)
        self.assertIsNone(history_args.limit)

    def test_top_import_and_completions_parsers(self) -> None:
        parser = build_parser()
        top_args = parser.parse_args(["top", "--limit", "3", "--project", "project"])
        import_args = parser.parse_args(["import", "a.json", "b.json"])
        completion_args = parser.parse_args(["completions", "zsh"])
        self.assertEqual(top_args.command, "top")
        self.assertEqual(top_args.limit, 3)
        self.assertEqual(top_args.project_name, "project")
        self.assertEqual(import_args.input, ["a.json", "b.json"])
        self.assertEqual(completion_args.shell, "zsh")

    def test_init_compare_named_and_report_parsers(self) -> None:
        parser = build_parser()
        init_args = parser.parse_args(["init", "--force"])
        compare_args = parser.parse_args(["compare", "today", "yesterday"])
        report_args = parser.parse_args(["report", "weekly", "--format", "html", "--project", "project", "--output", "weekly.html", "--render"])
        self.assertEqual(init_args.command, "init")
        self.assertTrue(init_args.force)
        self.assertEqual(compare_args.current, "today")
        self.assertEqual(compare_args.previous, "yesterday")
        self.assertEqual(report_args.period, "weekly")
        self.assertEqual(report_args.format, "html")
        self.assertEqual(report_args.project_name, "project")
        self.assertEqual(report_args.output, "weekly.html")
        self.assertTrue(report_args.render)

    def test_project_drilldown_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["project", "project", "--days", "30", "--json"])
        self.assertEqual(args.command, "project")
        self.assertEqual(args.name, "project")
        self.assertEqual(args.days, 30)
        self.assertTrue(args.json_output)

    def test_merge_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["merge", "merged.json", "a.json", "b.json", "--json"])
        self.assertEqual(args.command, "merge")
        self.assertEqual(args.output, "merged.json")
        self.assertEqual(args.input, ["a.json", "b.json"])
        self.assertTrue(args.json_output)

    def test_config_show_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["config", "show", "--json"])
        self.assertEqual(args.command, "config")
        self.assertEqual(args.config_command, "show")
        self.assertTrue(args.json_output)

    def test_write_report_output_and_browser_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = _write_report_output("<html></html>", str(Path(tmpdir) / "report.html"), html_mode=True)
            self.assertTrue(output_path.exists())
            self.assertIn("report.html", str(output_path))
        temp_output = _write_report_output("<html></html>", None, html_mode=True)
        self.assertTrue(temp_output.exists())
        with mock.patch("codex_stats.cli.webbrowser.open") as open_mock:
            _open_report_in_browser(temp_output)
        open_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
