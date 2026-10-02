from __future__ import annotations

import contextlib
import io
import os
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

    def test_write_dashboard_output_reuses_one_stable_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "cache" / "codex-stats" / "dashboard.html"
            first = _write_dashboard_output("<html>one</html>", target)
            second = _write_dashboard_output("<html>two</html>", target)
            # Overwriting in place is what lets a reopened bookmark refresh rather
            # than keep showing the previous run.
            self.assertEqual(first, second)
            self.assertEqual(second.read_text(encoding="utf-8"), "<html>two</html>\n")
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_write_dashboard_output_defaults_to_discovered_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": tmpdir}):
                output_path = _write_dashboard_output("<html></html>")
            self.assertEqual(output_path, Path(tmpdir) / "codex-stats" / "dashboard.html")
            self.assertTrue(output_path.exists())

    def test_open_report_in_browser_cache_busts_on_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "dashboard.html"
            target.write_text("<html>one</html>", encoding="utf-8")
            with mock.patch("codex_stats.cli.webbrowser.open") as open_mock:
                _open_report_in_browser(target)
            first_uri = open_mock.call_args[0][0]
            self.assertTrue(first_uri.endswith(f"?v={target.stat().st_mtime_ns}"))

            # Rewriting the same path must produce a different URL, or the browser
            # would serve its cached copy of the old dashboard.
            target.write_text("<html>two, and longer</html>", encoding="utf-8")
            with mock.patch("codex_stats.cli.webbrowser.open") as open_mock:
                _open_report_in_browser(target)
            second_uri = open_mock.call_args[0][0]
            self.assertNotEqual(first_uri, second_uri)
            self.assertTrue(second_uri.endswith(f"?v={target.stat().st_mtime_ns}"))

    def test_open_report_in_browser(self) -> None:
        with mock.patch("codex_stats.cli.webbrowser.open") as open_mock:
            _open_report_in_browser(Path("/tmp/dashboard.html"))
        open_mock.assert_called_once()

    def test_main_builds_and_opens_dashboard(self) -> None:
        stdout = io.StringIO()
        # Public submission is disabled unless an operator configures both a
        # private endpoint and a signing key.
        with mock.patch("codex_stats.cli.Paths.discover") as discover, mock.patch(
            "codex_stats.cli.format_dashboard_html", return_value="<html></html>"
        ), mock.patch("codex_stats.cli._open_report_in_browser") as open_mock, mock.patch(
            "codex_stats.cli._build_dashboard"
        ) as build_mock, mock.patch(
            "codex_stats.cli.LeaderboardConfig.from_env", return_value=None
        ), contextlib.redirect_stdout(stdout):
            exit_code = main([])
        self.assertEqual(exit_code, 0)
        build_mock.assert_called_once()
        discover.assert_called_once()
        open_mock.assert_called_once()
        self.assertIn("Opened dashboard in browser", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
