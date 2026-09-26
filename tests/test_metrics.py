from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import _build_dashboard, _build_window
from codex_stats.config import Paths, load_pricing_config
from codex_stats.display import format_dashboard_html, format_dashboard_svg_assets
from codex_stats.ingest import (
    _read_rollout,
    file_edits_from_patch,
    get_session,
    get_session_details,
    iter_session_details,
)
from codex_stats.metrics import (
    estimate_detail_cost,
    filter_details_by_project,
    local_date,
    summarize_activity_heatmap_from_details,
    summarize_badges,
    summarize_compare_from_details,
    summarize_costs_from_details,
    summarize_daily_from_details,
    summarize_details,
    summarize_expensive_session,
    summarize_files_from_details,
    summarize_history_from_details,
    summarize_insights_from_details,
    summarize_project_drilldowns_from_details,
    summarize_projects_from_details,
    summarize_source_breakdown_from_details,
    summarize_source_daily_from_details,
    summarize_takeaways,
    summarize_top_sessions_from_details,
    summarize_work_rhythm,
)
from codex_stats.models import DashboardData
from codex_stats.sources import _ingest_claude, iter_sources, source_label


def _details(paths: Paths, days: int, now: datetime | None = None) -> list:
    current_time = now or datetime.now().astimezone()
    end_day = current_time.date()
    start_day = end_day - timedelta(days=max(days, 1) - 1)
    return [
        detail
        for detail in iter_session_details(paths)
        if start_day <= local_date(detail.session.created_at, current_time.tzinfo) <= end_day
    ]


class MetricsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self._source_env_overrides = {
            "CODEX_STATS_OPENCODE_HOME": os.environ.get("CODEX_STATS_OPENCODE_HOME"),
            "CODEX_STATS_CLAUDE_PROJECTS_DIR": os.environ.get("CODEX_STATS_CLAUDE_PROJECTS_DIR"),
            "CODEX_STATS_HERMES_HOME": os.environ.get("CODEX_STATS_HERMES_HOME"),
        }
        os.environ["CODEX_STATS_OPENCODE_HOME"] = str(root / "empty-opencode")
        os.environ["CODEX_STATS_CLAUDE_PROJECTS_DIR"] = str(root / "empty-claude")
        os.environ["CODEX_STATS_HERMES_HOME"] = str(root / "empty-hermes")
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
            {
                "timestamp": "2026-04-03T13:18:24.100Z",
                "type": "event_msg",
                "payload": {
                    "type": "agent_message",
                    "agent_message": {
                        "tool_call": {
                            "name": "mcp__update_file",
                            "arguments": json.dumps(
                                {
                                    "file_path": "src/main.py",
                                    "old_string": "def main():\n    return\n",
                                    "new_string": "def main():\n    return 42\n",
                                }
                            ),
                        }
                    },
                },
            },
            {
                "timestamp": "2026-04-03T13:18:24.200Z",
                "type": "event_msg",
                "payload": {
                    "type": "mcp__create_file",
                    "mcp__create_file": {
                        "file_path": "src/new_module.py",
                        "content": "print('hello')\nprint('world')\n",
                    },
                },
            },
        ]
        rollout_path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
        self.paths = Paths(
            codex_home=codex_home,
            state_db=self.state_db,
            sessions_dir=codex_home / "sessions",
            config_dir=codex_home / "config",
            config_file=codex_home / "config" / "config.toml",
        )

    def tearDown(self) -> None:
        for key, value in self._source_env_overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmpdir.cleanup()

    def test_session_details_are_read_from_local_state(self) -> None:
        session = get_session(self.paths, "session-1")
        assert session is not None
        details = get_session_details(self.paths, session)
        self.assertEqual(details.request_count, 2)
        self.assertEqual(details.input_tokens, 250)
        self.assertEqual(details.output_tokens, 30)
        self.assertEqual(details.effective_total_tokens(), 280)
        self.assertEqual(len(details.file_edits), 2)
        update, created = details.file_edits
        self.assertEqual((update.path, update.action, update.insertions, update.deletions), ("src/main.py", "updated", 1, 1))
        self.assertEqual((created.path, created.action, created.insertions, created.deletions), ("src/new_module.py", "created", 2, 0))

    def test_file_impact_aggregation_and_dashboard(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        details = _details(self.paths, 7, now=now)
        impact = summarize_files_from_details(details)
        self.assertEqual(len(impact), 2)
        main, module = impact
        self.assertEqual(main.path, "src/main.py")
        self.assertEqual(main.edits, 1)
        self.assertEqual(main.sessions, 1)
        self.assertEqual((main.insertions, main.deletions), (1, 1))
        self.assertEqual(main.updated, 1)
        self.assertEqual(module.path, "src/new_module.py")
        self.assertEqual(module.created, 1)
        self.assertEqual(module.insertions, 2)
        self.assertEqual(sum(entry.edits for entry in impact), 2)
        dashboard = _build_dashboard(self.paths, now=now)
        html = format_dashboard_html(dashboard)
        self.assertIn("Most Edited Files", html)
        self.assertIn("src/main.py", html)
        self.assertEqual(impact[0].to_dict()["path"], "src/main.py")

    def test_takeaway_mentions_file_work(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        details = _details(self.paths, 7, now=now)
        summary = summarize_details("last 7 days", details)
        insights = summarize_insights_from_details(details, month=summary, now=now)
        file_impact = summarize_files_from_details(details)
        takeaways = summarize_takeaways(
            summary=summary,
            insights=insights,
            file_impact=file_impact,
            max_items=5,
        )
        self.assertTrue(any("adding 3 lines and removing 1 lines" in item for item in takeaways))

    def test_claude_transcript_parses_file_edits(self) -> None:
        projects_dir = Path(self.tmpdir.name) / "claude-projects"
        project_dir = projects_dir / "tmp-claude-project"
        project_dir.mkdir(parents=True)
        transcript = [
            {
                "timestamp": "2026-04-03T13:17:23.324Z",
                "type": "user",
                "cwd": "/tmp/claude-project",
                "message": {"role": "user", "content": "hi"},
            },
            {
                "timestamp": "2026-04-03T13:17:25.324Z",
                "type": "assistant",
                "cwd": "/tmp/claude-project",
                "message": {
                    "model": "claude-opus-4",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": "src/app.py", "old_string": "old", "new_string": "brand new line"},
                        },
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": "src/new.txt", "content": "line1\nline2"},
                        },
                    ],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            },
        ]
        (project_dir / "abc123.jsonl").write_text(
            "\n".join(json.dumps(event) for event in transcript),
            encoding="utf-8",
        )
        details = _ingest_claude(projects_dir)
        self.assertEqual(len(details), 1)
        edits = details[0].file_edits
        self.assertEqual(len(edits), 2)
        edit_block, write_block = edits
        self.assertEqual(edit_block.path, "src/app.py")
        self.assertEqual(edit_block.action, "updated")
        self.assertEqual((edit_block.insertions, edit_block.deletions), (1, 1))
        self.assertEqual(write_block.path, "src/new.txt")
        self.assertEqual(write_block.action, "created")
        self.assertEqual(write_block.insertions, 2)

    def test_parse_custom_tool_call_apply_patch(self) -> None:
        patch = (
            "*** Begin Patch\n"
            "*** Add File: /tmp/thing.py\n"
            "+def greet():\n"
            "+    return 'hi'\n"
            "*** Update File: /tmp/app.py\n"
            "@@\n"
            "-old\n"
            "+new\n"
            "@@\n"
            "+extra\n"
            "*** Delete File: /tmp/rolledup.txt\n"
            "-gone\n"
            "*** End Patch\n"
        )
        event = {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "status": "completed",
                "input": patch,
            },
        }
        rollout = Path(self.tmpdir.name) / "rollout-apply.jsonl"
        rollout.write_text(json.dumps(event) + "\n", encoding="utf-8")
        _, edits = _read_rollout(rollout)
        by = {(e.action, e.path): (e.insertions, e.deletions) for e in edits}
        self.assertEqual(by[("created", "/tmp/thing.py")], (2, 0))
        self.assertEqual(by[("updated", "/tmp/app.py")], (2, 1))
        self.assertEqual(by[("deleted", "/tmp/rolledup.txt")], (0, 1))

    def test_file_edits_from_patch_splits_multiple_files(self) -> None:
        patch = (
            "*** Begin Patch\n"
            "*** Update File: a.py\n"
            "@@ -1,2 +1,3 @@\n"
            "-x\n"
            "+y\n"
            "+z\n"
            "*** Add File: b.py\n"
            "+print('b')\n"
            "*** End Patch\n"
        )
        edits = file_edits_from_patch("apply_patch", patch)
        self.assertEqual({(e.path, e.action) for e in edits}, {("a.py", "updated"), ("b.py", "created")})
        self.assertEqual(edits[0].insertions, 2)
        self.assertEqual(edits[0].deletions, 1)

    def test_projects_history_costs_and_insights(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        details = _details(self.paths, 7, now=now)
        pricing = load_pricing_config(self.paths)
        projects = summarize_projects_from_details(details, pricing)
        history = summarize_history_from_details(details, pricing, limit=5)
        costs = summarize_costs_from_details(
            details,
            pricing=pricing,
            today=summarize_details("today", details, pricing),
            week=summarize_details("week", details, pricing),
            month=summarize_details("month", details, pricing),
            now=now,
        )
        insights = summarize_insights_from_details(details, pricing=pricing, now=now)
        self.assertEqual(projects[0].name, "project")
        self.assertEqual(projects[0].requests, 2)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].project_name, "project")
        self.assertGreater(costs.month_cost_usd, 0.0)
        self.assertEqual(insights.large_session_count, 0)
        self.assertGreater(insights.average_tokens_per_request, 0.0)
        self.assertIn("Heavy cost concentration in one session", insights.anomalies)
        self.assertIn("Low cache efficiency", insights.anomalies)
        self.assertIn("Split exploratory work into smaller sessions.", insights.recommendations)

    def test_daily_and_compare_from_details(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        details = _details(self.paths, 7, now=now)
        daily = summarize_daily_from_details(details, days=7, now=now)
        compare = summarize_compare_from_details(
            details,
            [],
            current_label="last 7 days",
            previous_label="prev 7 days",
        )
        self.assertEqual(len(daily), 7)
        self.assertEqual(daily[-1].total_tokens, 280)
        self.assertEqual(compare.current.total_tokens, 280)
        self.assertEqual(compare.previous.total_tokens, 0)

    def test_top_sessions(self) -> None:
        details = _details(self.paths, 7, now=datetime.fromisoformat("2026-04-03T18:30:00+05:30"))
        top = summarize_top_sessions_from_details(details, limit=1)
        self.assertEqual(top[0].project_name, "project")

    def test_project_drilldown_and_filtered_top(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        details = _details(self.paths, 30, now=now)
        pricing = load_pricing_config(self.paths)
        summary = summarize_details(
            "project",
            filter_details_by_project(details, "project"),
            pricing,
        )
        drilldowns = summarize_project_drilldowns_from_details(details, days=30, now=now, pricing=pricing)
        top = summarize_top_sessions_from_details(details, limit=5, project_name="project")
        self.assertEqual(summary.total_tokens, 280)
        self.assertEqual(summary.requests, 2)
        self.assertEqual(len(drilldowns), 1)
        self.assertEqual(drilldowns[0].name, "project")
        self.assertEqual(drilldowns[0].summary.total_tokens, 280)
        self.assertGreaterEqual(len(drilldowns[0].takeaways), 1)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].project_name, "project")

    def test_takeaways_summarize_usage_story(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        details = _details(self.paths, 7, now=now)
        summary = summarize_details("last 7 days", details)
        compare = summarize_compare_from_details(details, [], current_label="last 7 days", previous_label="prev 7 days")
        insights = summarize_insights_from_details(details, month=summary, now=now)
        costs = summarize_costs_from_details(details, today=summary, week=summary, month=summary, now=now)
        takeaways = summarize_takeaways(summary=summary, comparison=compare, insights=insights, costs=costs)
        self.assertTrue(any("Cache reuse is low" in item for item in takeaways))
        self.assertTrue(any("Current pace projects" in item for item in takeaways))

    def test_badges_and_expensive_session(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        details = _details(self.paths, 7, now=now)
        summary = summarize_details("last 7 days", details)
        daily = summarize_daily_from_details(details, days=7, now=now)
        heatmap = summarize_activity_heatmap_from_details(details, timezone=now.tzinfo)
        badges = summarize_badges(summary=summary, daily_points=daily, activity_heatmap=heatmap)
        expensive_session = summarize_expensive_session(details)
        self.assertTrue(any(badge.label == "Top model" and badge.value == "gpt-5.4" for badge in badges))
        self.assertTrue(any(badge.label == "Busiest day" for badge in badges))
        self.assertIsNotNone(expensive_session)
        assert expensive_session is not None
        self.assertEqual(expensive_session.project_name, "project")
        self.assertEqual(expensive_session.total_tokens, 280)

    def test_work_rhythm_summary(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        details = _details(self.paths, 7, now=now)
        daily = summarize_daily_from_details(details, days=7, now=now)
        heatmap = summarize_activity_heatmap_from_details(details, timezone=now.tzinfo)
        rhythm = summarize_work_rhythm(daily, heatmap)
        self.assertIn("work", rhythm.headline.lower())
        self.assertIsNotNone(rhythm.peak_day)
        self.assertIsNotNone(rhythm.peak_hour)

    def test_dashboard_html_output(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        html = format_dashboard_html(dashboard)
        week_assets = format_dashboard_svg_assets(dashboard.windows[1], scope_label="Overview")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Every tool, one view.", html)
        self.assertIn("The selected tab updates the full page.", html)
        self.assertIn("Copy Summary", html)
        self.assertIn("data-copy-feedback", html)
        self.assertIn("Download PDF", html)
        self.assertIn("Full Page JPG", html)
        self.assertIn("Summary JPG", html)
        self.assertIn("Most Expensive Session", html)
        self.assertIn("Busiest day", html)
        self.assertIn("Peak hour", html)
        self.assertIn("Work Rhythm", html)
        self.assertIn('data-window="day"', html)
        self.assertIn('data-window="week"', html)
        self.assertIn('data-window="month"', html)
        self.assertIn('data-window="all"', html)
        self.assertIn("Overview Stats Week", html)
        self.assertIn("Top project: project with 280 tokens across 2 requests.", html)
        self.assertIn("Key Takeaways", html)
        self.assertIn("Project Drilldown", html)
        self.assertIn("Project Token Trend", html)
        self.assertIn('data-project-target="overview-week-project-0"', html)
        self.assertIn("Projects, Sessions, and History", html)
        self.assertEqual(set(week_assets), {"page-card", "summary-card", "cost-card", "focus-card", "projects-card", "heatmap-card"})
        self.assertIn("Single-image export of the active dashboard view.", week_assets["page-card"])
        self.assertIn("Overview Stats Week", week_assets["summary-card"])
        self.assertIn("WINDOW TOTAL", week_assets["cost-card"])
        self.assertIn("Heatmap", week_assets["heatmap-card"])

    def test_dashboard_costs_are_scoped_per_window(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        pricing = load_pricing_config(self.paths)
        base_detail = get_session_details(self.paths, get_session(self.paths))
        older_session = replace(
            base_detail.session,
            session_id="session-2",
            created_at=base_detail.session.created_at - timedelta(days=20),
            updated_at=base_detail.session.updated_at - timedelta(days=20),
            tokens_used=base_detail.session.tokens_used * 4,
        )
        older_detail = replace(
            base_detail,
            session=older_session,
            request_count=base_detail.request_count * 3,
            input_tokens=(base_detail.input_tokens or 0) * 4,
            output_tokens=(base_detail.output_tokens or 0) * 4,
            cached_input_tokens=(base_detail.cached_input_tokens or 0) * 4,
            reasoning_output_tokens=(base_detail.reasoning_output_tokens or 0) * 4,
            total_tokens_from_rollout=(base_detail.total_tokens_from_rollout or 0) * 4,
            started_at=(base_detail.started_at - timedelta(days=20)) if base_detail.started_at else None,
        )
        day_window = _build_window(
            key="day",
            label="Day",
            description="Day view",
            current_details=[base_detail],
            previous_details=[],
            current_label="today",
            previous_label="yesterday",
            trend_days=1,
            all_details=[base_detail, older_detail],
            pricing=pricing,
            now=now,
        )
        month_window = _build_window(
            key="month",
            label="Month",
            description="Month view",
            current_details=[base_detail, older_detail],
            previous_details=[],
            current_label="last 30 days",
            previous_label="previous 30 days",
            trend_days=30,
            all_details=[base_detail, older_detail],
            pricing=pricing,
            now=now,
        )
        self.assertEqual(day_window.costs.today_cost_usd, day_window.summary.estimated_cost_usd)
        self.assertEqual(month_window.costs.today_cost_usd, month_window.summary.estimated_cost_usd)
        self.assertGreater(month_window.costs.today_cost_usd, day_window.costs.today_cost_usd)
        self.assertGreater(month_window.costs.highest_session_cost_usd, day_window.costs.highest_session_cost_usd)
        self.assertGreaterEqual(len(day_window.takeaways), 1)
        self.assertGreaterEqual(len(day_window.badges), 1)
        self.assertIsNotNone(day_window.expensive_session)
        self.assertIsNotNone(day_window.work_rhythm)
        self.assertEqual(len(day_window.project_drilldowns), 1)
        self.assertEqual(day_window.project_drilldowns[0].name, "project")

    def test_dashboard_scopes_cover_all_tools(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        self.assertEqual(
            [scope.key for scope in dashboard.scopes],
            ["overview", "codex", "opencode", "claude", "hermes"],
        )
        self.assertEqual(len(dashboard.windows), 20)
        for scope in dashboard.scopes:
            self.assertEqual([window.key for window in scope.windows], ["day", "week", "month", "all"])
            self.assertEqual(scope.windows[1].label, "Week")
        self.assertEqual(dashboard.windows[0].key, "day")
        self.assertEqual(dashboard.windows[1].key, "week")
        overview_week = dashboard.windows[1]
        self.assertEqual(overview_week.summary.label, "last 7 days")
        self.assertIsNotNone(overview_week.tool_breakdown)
        assert overview_week.tool_breakdown is not None
        self.assertEqual([entry.name for entry in overview_week.tool_breakdown], ["Codex"])
        self.assertEqual(overview_week.tool_breakdown[0].total_tokens, 280)
        self.assertIsNotNone(overview_week.tool_daily_points)
        self.assertIsNone(dashboard.scopes[1].windows[1].tool_daily_points)
        self.assertIsNone(dashboard.scopes[1].windows[1].tool_breakdown)

    def test_windows_only_dashboard_gets_overview_scope(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        empty_window = _build_window(
            key="day",
            label="Day",
            description="Day view",
            current_details=[],
            previous_details=[],
            current_label="today",
            previous_label="yesterday",
            trend_days=1,
            all_details=[],
            pricing=load_pricing_config(self.paths),
            now=now,
        )
        dashboard = DashboardData(generated_at=now, windows=[empty_window])
        self.assertEqual([scope.key for scope in dashboard.scopes], ["overview"])
        self.assertEqual(dashboard.scopes[0].label, "Overview")
        self.assertEqual(len(dashboard.windows), 1)
        round_trip = dashboard.to_dict()
        self.assertEqual(round_trip["scopes"][0]["key"], "overview")

    def test_source_ingesters_skip_missing_data(self) -> None:
        sources = iter_sources(self.paths)
        self.assertEqual([source.key for source in sources], ["codex", "opencode", "claude", "hermes"])
        self.assertTrue(sources[0].available)
        self.assertFalse(any(source.available for source in sources[1:]))
        self.assertEqual(len(sources[0].ingest()), 1)
        for source in sources[1:]:
            self.assertEqual(source.ingest(), [])

    def test_source_breakdown_sums_usage(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        pricing = load_pricing_config(self.paths)
        base_detail = get_session_details(self.paths, get_session(self.paths))
        codex_detail = replace(
            base_detail,
            session=replace(base_detail.session, source="codex", tokens_used=base_detail.session.tokens_used, session_id="session-1"),
        )
        opencode_detail = replace(
            codex_detail,
            session=replace(codex_detail.session, source="opencode", session_id="session-2", tokens_used=codex_detail.session.tokens_used),
            request_count=codex_detail.request_count,
        )
        entries = summarize_source_breakdown_from_details([codex_detail, opencode_detail], pricing)
        self.assertEqual([entry.name for entry in entries], ["Codex", "OpenCode"])
        self.assertEqual([entry.sessions for entry in entries], [1, 1])
        self.assertEqual([entry.requests for entry in entries], [2, 2])
        self.assertEqual([entry.total_tokens for entry in entries], [280, 280])
        self.assertGreater(entries[0].estimated_cost_usd, 0)

    def test_source_label_falls_back(self) -> None:
        self.assertEqual(source_label("codex"), "Codex")
        self.assertEqual(source_label("claude"), "Claude Code")
        self.assertEqual(source_label("pi"), "Pi")

    def test_recorded_cost_wins_over_estimate(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        pricing = load_pricing_config(self.paths)
        base_detail = get_session_details(self.paths, get_session(self.paths))
        estimated = estimate_detail_cost(base_detail, pricing)
        with_cost = replace(base_detail, recorded_cost_usd=12.5)
        self.assertEqual(estimate_detail_cost(with_cost, pricing), 12.5)
        with_zero_cost = replace(base_detail, recorded_cost_usd=0.0)
        self.assertEqual(estimate_detail_cost(with_zero_cost, pricing), estimated)
        self.assertGreater(estimated, 0)

    def test_source_daily_trend_points(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        pricing = load_pricing_config(self.paths)
        base_detail = get_session_details(self.paths, get_session(self.paths))
        codex_detail = replace(
            base_detail,
            session=replace(base_detail.session, source="codex", session_id="session-1", created_at=now - timedelta(days=1)),
        )
        opencode_detail = replace(
            codex_detail,
            session=replace(codex_detail.session, source="opencode", session_id="session-2"),
        )
        points = summarize_source_daily_from_details(
            [codex_detail, opencode_detail],
            days=7,
            now=now,
            pricing=pricing,
        )
        self.assertEqual(len(points), 2)
        self.assertEqual({point.source for point in points}, {"codex", "opencode"})
        for point in points:
            self.assertEqual(point.total_tokens, 280)
            self.assertGreater(point.estimated_cost_usd, 0)
        outside = summarize_source_daily_from_details(
            [codex_detail],
            days=7,
            now=now,
            pricing=pricing,
        )
        self.assertTrue(any(point.source == "codex" for point in outside))

    def test_dashboard_includes_every_detected_source(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        self.assertEqual(
            [scope.key for scope in dashboard.scopes],
            ["overview", "codex", "opencode", "claude", "hermes"],
        )

    def test_dashboard_html_includes_work_patterns_and_heatmap(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        html = format_dashboard_html(dashboard)
        self.assertIn("Work Patterns", html)
        self.assertIn("Activity Heatmap", html)
        self.assertIn("Top project concentration", html)

    def test_empty_state_showcase_appears_for_no_data(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        empty_window = _build_window(
            key="day",
            label="Day",
            description="Day view",
            current_details=[],
            previous_details=[],
            current_label="today",
            previous_label="yesterday",
            trend_days=1,
            all_details=[],
            pricing=load_pricing_config(self.paths),
            now=now,
        )
        html = format_dashboard_html(DashboardData(generated_at=now, windows=[empty_window]))
        self.assertIn("Still learning your rhythm.", html)
        self.assertIn("No project drilldown yet.", html)
        self.assertIn("No activity map yet.", html)


if __name__ == "__main__":
    unittest.main()