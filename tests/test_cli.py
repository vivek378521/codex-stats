from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import _open_report_in_browser, _write_dashboard_output, build_parser


class CliTestCase(unittest.TestCase):
    def test_default_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.command)
        self.assertIsNone(args.dashboard_output)
        self.assertFalse(args.no_open)

    def test_dashboard_parser_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--output", "dashboard.html", "--no-open"])
        self.assertEqual(args.dashboard_output, "dashboard.html")
        self.assertTrue(args.no_open)

    def test_export_parser(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["export", "stats.json", "--since", "30d"])
        self.assertEqual(args.command, "export")
        self.assertEqual(args.output, "stats.json")
        self.assertEqual(args.since, "30d")

    def test_write_dashboard_output_and_browser_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = _write_dashboard_output("<html></html>", str(Path(tmpdir) / "dashboard.html"))
            self.assertTrue(output_path.exists())
            self.assertIn("dashboard.html", str(output_path))
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = _write_dashboard_output("<html></html>", None)
            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.suffix, ".html")
        with mock.patch("codex_stats.cli.webbrowser.open") as open_mock:
            _open_report_in_browser(output_path)
        open_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
