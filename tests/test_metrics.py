from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.config import Paths
from codex_stats.ingest import get_session, get_session_details
from codex_stats.metrics import (
    details_for_last_days,
    build_report,
    run_doctor,
    summarize_compare_named,
    summarize_compare,
    summarize_costs,
    summarize_daily,
    summarize_history,
    summarize_insights,
    summarize_models,
    summarize_month,
    summarize_projects,
    summarize_today,
    summarize_top_sessions,
    summarize_week,
)
from codex_stats.transfer import export_payload, read_import, read_imports


class MetricsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        codex_home = root / ".codex"
        sessions_dir = codex_home / "sessions" / "2026" / "04" / "03"
        sessions_dir.mkdir(parents=True)
        self.state_db = codex_home / "state_5.sqlite"
        rollout_path = sessions_dir / "rollout-test.jsonl"

        connection = sqlite3.connect(self.state_db)
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                has_user_event INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                archived_at INTEGER,
                git_sha TEXT,
                git_branch TEXT,
                git_origin_url TEXT,
                cli_version TEXT NOT NULL DEFAULT '',
                first_user_message TEXT NOT NULL DEFAULT '',
                agent_nickname TEXT,
                agent_role TEXT,
                memory_mode TEXT NOT NULL DEFAULT 'enabled',
                model TEXT,
                reasoning_effort TEXT,
                agent_path TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source, model_provider, cwd,
                title, sandbox_policy, approval_mode, tokens_used, model
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "session-1",
                str(rollout_path),
                1775222209,
                1775222447,
                "cli",
                "openai",
                "/tmp/project",
                "Test Thread",
                "workspace-write",
                "default",
                223342,
                "gpt-5.4",
            ),
        )
        connection.commit()
        connection.close()

        lines = [
            {
                "timestamp": "2026-04-03T13:17:23.324Z",
                "type": "session_meta",
                "payload": {"timestamp": "2026-04-03T13:16:49.765Z"},
            },
            {
                "timestamp": "2026-04-03T13:17:23.325Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "first"},
            },
            {
                "timestamp": "2026-04-03T13:17:23.740Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 10,
                            "reasoning_output_tokens": 3,
                            "total_tokens": 110,
                        }
                    },
                },
            },
            {
                "timestamp": "2026-04-03T13:18:23.325Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "second"},
            },
            {
                "timestamp": "2026-04-03T13:18:23.740Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 250,
                            "cached_input_tokens": 50,
                            "output_tokens": 30,
                            "reasoning_output_tokens": 7,
                            "total_tokens": 280,
                        }
                    },
                },
            },
        ]
        rollout_path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
        self.paths = Paths(
            codex_home=codex_home,
            state_db=self.state_db,
            logs_db=codex_home / "logs_1.sqlite",
            sessions_dir=codex_home / "sessions",
            config_dir=codex_home / "config",
            config_file=codex_home / "config" / "config.toml",
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_session_details_are_read_from_local_state(self) -> None:
        session = get_session(self.paths, "session-1")
        assert session is not None
        details = get_session_details(self.paths, session)
        self.assertEqual(details.request_count, 2)
        self.assertEqual(details.input_tokens, 250)
        self.assertEqual(details.output_tokens, 30)
        self.assertEqual(details.effective_total_tokens(), 280)

    def test_today_summary_aggregates_sessions(self) -> None:
        summary = summarize_today(self.paths, now=datetime.fromisoformat("2026-04-03T18:30:00+05:30"))
        self.assertEqual(summary.sessions, 1)
        self.assertEqual(summary.requests, 2)
        self.assertEqual(summary.total_tokens, 280)
        self.assertEqual(summary.top_model, "gpt-5.4")

    def test_week_and_month_summaries_include_session(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        week = summarize_week(self.paths, now=now)
        month = summarize_month(self.paths, now=now)
        self.assertEqual(week.total_tokens, 280)
        self.assertEqual(month.total_tokens, 280)

    def test_model_and_project_breakdowns(self) -> None:
        models = summarize_models(self.paths)
        projects = summarize_projects(self.paths)
        self.assertEqual(models[0].name, "gpt-5.4")
        self.assertEqual(models[0].total_tokens, 280)
        self.assertEqual(projects[0].name, "project")
        self.assertEqual(projects[0].requests, 2)

    def test_history_costs_and_insights(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        history = summarize_history(self.paths, limit=5)
        costs = summarize_costs(self.paths, now=now)
        insights = summarize_insights(self.paths, now=now)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].project_name, "project")
        self.assertGreater(costs.month_cost_usd, 0.0)
        self.assertEqual(insights.large_session_count, 0)
        self.assertGreater(insights.average_tokens_per_request, 0.0)

    def test_export_and_import_round_trip(self) -> None:
        payload = export_payload(self.paths)
        export_path = Path(self.tmpdir.name) / "export.json"
        export_path.write_text(json.dumps(payload), encoding="utf-8")
        imported = read_import(export_path)
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0].session.project_name, "project")

    def test_details_for_last_days(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        details = details_for_last_days(self.paths, 7, now=now)
        self.assertEqual(len(details), 1)

    def test_daily_compare_and_doctor(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        daily = summarize_daily(self.paths, days=7, now=now)
        compare = summarize_compare(self.paths, days=7, now=now)
        checks = run_doctor(self.paths)
        self.assertEqual(len(daily), 7)
        self.assertEqual(daily[-1].total_tokens, 280)
        self.assertEqual(compare.current.total_tokens, 280)
        self.assertTrue(any(check.name == "state_db" and check.ok for check in checks))

    def test_top_sessions_and_multi_import(self) -> None:
        top = summarize_top_sessions(self.paths, limit=1)
        self.assertEqual(top[0].project_name, "project")
        payload = export_payload(self.paths)
        export_path_a = Path(self.tmpdir.name) / "a.json"
        export_path_b = Path(self.tmpdir.name) / "b.json"
        export_path_a.write_text(json.dumps(payload), encoding="utf-8")
        export_path_b.write_text(json.dumps(payload), encoding="utf-8")
        merged = read_imports([export_path_a, export_path_b])
        self.assertEqual(len(merged), 1)

    def test_compare_named_and_report(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        report = summarize_compare_named(self.paths, "today", "yesterday", now=now)
        weekly = build_report(self.paths, "weekly", now=now)
        self.assertEqual(report.current.total_tokens, 280)
        self.assertEqual(report.previous.total_tokens, 0)
        self.assertEqual(weekly.period, "weekly")
        self.assertEqual(weekly.summary.total_tokens, 280)


if __name__ == "__main__":
    unittest.main()
