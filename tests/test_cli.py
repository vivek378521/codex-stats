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


if __name__ == "__main__":
    unittest.main()
