from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import _open_report_in_browser, _write_dashboard_output, build_parser, main


class CliTestCase(unittest.TestCase):
    def test_parser_takes_no_options(self) -> None:
        parser = build_parser()
        self.assertEqual(vars(parser.parse_args([])), {})
        for removed in ("--output", "--no-open", "--source", "export"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parser.parse_args([removed])

    def test_write_dashboard_output_uses_temp_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("codex_stats.cli.tempfile.NamedTemporaryFile") as temp_file:
                temp_file.return_value.name = str(Path(tmpdir) / "dashboard.html")
                output_path = _write_dashboard_output("<html></html>")
            self.assertTrue(output_path.exists())
            self.assertEqual(output_path.suffix, ".html")
            self.assertIn("dashboard.html", str(output_path))

    def test_open_report_in_browser(self) -> None:
        with mock.patch("codex_stats.cli.webbrowser.open") as open_mock:
            _open_report_in_browser(Path("/tmp/dashboard.html"))
        open_mock.assert_called_once()

    def test_main_builds_and_opens_dashboard(self) -> None:
        stdout = io.StringIO()
        with mock.patch("codex_stats.cli.Paths.discover") as discover, mock.patch(
            "codex_stats.cli.format_dashboard_html", return_value="<html></html>"
        ), mock.patch("codex_stats.cli._open_report_in_browser") as open_mock, mock.patch(
            "codex_stats.cli._build_dashboard"
        ) as build_mock, contextlib.redirect_stdout(stdout):
            exit_code = main([])
        self.assertEqual(exit_code, 0)
        build_mock.assert_called_once()
        discover.assert_called_once()
        open_mock.assert_called_once()
        self.assertIn("Opened dashboard in browser", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
