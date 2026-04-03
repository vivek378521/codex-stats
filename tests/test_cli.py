from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import build_parser


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
        self.assertEqual(export_args.command, "export")
        self.assertEqual(export_args.output, "stats.json")
        self.assertEqual(export_args.since, "30d")
        self.assertEqual(import_args.command, "import")
        self.assertTrue(import_args.json_output)

    def test_daily_compare_doctor_parsers(self) -> None:
        parser = build_parser()
        daily_args = parser.parse_args(["daily", "--days", "14"])
        compare_args = parser.parse_args(["compare", "--days", "14", "--json"])
        doctor_args = parser.parse_args(["doctor", "--strict"])
        self.assertEqual(daily_args.command, "daily")
        self.assertEqual(daily_args.days, 14)
        self.assertEqual(compare_args.command, "compare")
        self.assertTrue(compare_args.json_output)
        self.assertEqual(doctor_args.command, "doctor")
        self.assertTrue(doctor_args.strict)

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
        report_args = parser.parse_args(["report", "weekly", "--format", "markdown", "--project", "project", "--output", "weekly.md"])
        self.assertEqual(init_args.command, "init")
        self.assertTrue(init_args.force)
        self.assertEqual(compare_args.current, "today")
        self.assertEqual(compare_args.previous, "yesterday")
        self.assertEqual(report_args.period, "weekly")
        self.assertEqual(report_args.format, "markdown")
        self.assertEqual(report_args.project_name, "project")
        self.assertEqual(report_args.output, "weekly.md")

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


if __name__ == "__main__":
    unittest.main()
