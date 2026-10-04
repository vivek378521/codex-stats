from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import _build_dashboard, _build_window
from codex_stats.config import Paths, PricingConfig, load_pricing_config
from codex_stats.display import (
    _default_dashboard_view,
    format_dashboard_html,
    format_dashboard_svg_assets,
)
from codex_stats.ingest import (
    DEFAULT_MAX_SESSIONS,
    ENV_MAX_SESSIONS,
    _read_rollout,
    codex_session_coverage,
    file_edits_from_patch,
    get_session,
    get_session_details,
    iter_session_details,
    resolve_max_sessions,
)
from codex_stats.metrics import (
    estimate_detail_cost,
    uses_recorded_cost,
    filter_details_by_project,
    local_date,
    model_vendor,
    summarize_activity_heatmap_from_details,
    summarize_badges,
    summarize_branch_takeaways,
    summarize_branches_from_details,
    summarize_compare_from_details,
    summarize_costs_from_details,
    summarize_daily_from_details,
    summarize_details,
    summarize_efficiency_from_details,
    summarize_efficiency_takeaways,
    summarize_expensive_session,
    summarize_files_from_details,
    summarize_history_from_details,
    summarize_insights_from_details,
    summarize_project_drilldowns_from_details,
    summarize_projects_from_details,
    summarize_providers_from_details,
    summarize_source_breakdown_from_details,
    summarize_source_daily_from_details,
    summarize_takeaways,
    summarize_top_sessions_from_details,
    summarize_tool_efficiency_from_details,
    summarize_work_rhythm,
    UNIDENTIFIED_VENDOR_LABEL,
)
from codex_stats.models import (
    CACHED_SEPARATE,
    CACHED_WITHIN_INPUT,
    BehaviorSummary,
    DailyPoint,
    DashboardData,
    FileEdit,
    SessionDetails,
    SessionRecord,
)
from codex_stats.sources import (
    _ingest_claude,
    _ingest_hermes,
    _ingest_opencode,
    iter_sources,
    source_label,
)


def _isolate_sources(test: unittest.TestCase, root: Path) -> None:
    """Point the three non-Codex sources at empty dirs for the duration of a test.

    Only Codex is reached through ``Paths``; the other three resolve their own
    locations from the environment. Without this, a test that builds a dashboard
    silently merges whatever the developer happens to have installed locally, so
    the run passes or fails depending on whose machine it is on.
    """
    for var, name in (
        ("CODEX_STATS_OPENCODE_HOME", "empty-opencode"),
        ("CODEX_STATS_CLAUDE_PROJECTS_DIR", "empty-claude"),
        ("CODEX_STATS_HERMES_HOME", "empty-hermes"),
    ):
        previous = os.environ.get(var)
        test.addCleanup(os.environ.pop, var, None)
        if previous is not None:
            test.addCleanup(os.environ.__setitem__, var, previous)
        os.environ[var] = str(root / name)


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
        _isolate_sources(self, root)
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
            output_dir=codex_home / "cache",
            dashboard_file=codex_home / "cache" / "dashboard.html",
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
        self.assertEqual(len(details.file_edits), 2)
        update, created = details.file_edits
        self.assertEqual((update.path, update.action, update.insertions, update.deletions), ("src/main.py", "updated", 1, 1))
        self.assertEqual((created.path, created.action, created.insertions, created.deletions), ("src/new_module.py", "created", 2, 0))

    def _window_with_activity(self, base, *, key: str, sessions: int, active_days: int):
        """Copy a real window, overriding session count and how many days have tokens."""
        points = [
            DailyPoint(day=f"2026-04-{index + 1:02d}", total_tokens=1000, requests=2, estimated_cost_usd=0.1)
            for index in range(active_days)
        ]
        return replace(
            base,
            key=key,
            label=key,
            summary=replace(base.summary, sessions=sessions),
            daily_points=points,
        )

    def test_default_view_lands_on_narrowest_window_that_has_a_trend(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        base = dashboard.scopes[0].windows[0]
        scope = replace(
            dashboard.scopes[0],
            windows=[
                # Today has plenty of sessions but only one day, so it cannot
                # show a trend and must not win the default.
                self._window_with_activity(base, key="day", sessions=9, active_days=1),
                self._window_with_activity(base, key="week", sessions=2, active_days=3),
                self._window_with_activity(base, key="all", sessions=40, active_days=12),
            ],
        )
        self.assertEqual(_default_dashboard_view([scope], ["day", "week", "all"]), ("overview", "week"))

    def test_default_view_falls_back_to_narrowest_window_when_no_trend_exists(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        base = dashboard.scopes[0].windows[0]
        scope = replace(
            dashboard.scopes[0],
            windows=[
                self._window_with_activity(base, key="day", sessions=3, active_days=1),
                self._window_with_activity(base, key="week", sessions=4, active_days=1),
            ],
        )
        self.assertEqual(_default_dashboard_view([scope], ["day", "week"]), ("overview", "day"))

    def test_default_view_uses_first_tabs_when_nothing_was_recorded(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        base = dashboard.scopes[0].windows[0]
        scope = replace(
            dashboard.scopes[0],
            windows=[
                self._window_with_activity(base, key="day", sessions=0, active_days=0),
                self._window_with_activity(base, key="week", sessions=0, active_days=0),
            ],
        )
        self.assertEqual(_default_dashboard_view([scope], ["day", "week"]), ("overview", "day"))

    def test_dashboard_marks_the_chosen_view_active(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        scope_key, window_key = _default_dashboard_view(
            dashboard.scopes, [window.key for window in dashboard.windows]
        )
        html = format_dashboard_html(dashboard)
        self.assertIn(f'data-default-scope="{scope_key}" data-default-window="{window_key}"', html)
        self.assertEqual(html.count('<section class="window is-active"'), 1)
        self.assertIn(
            f'<section class="window is-active" data-window="{window_key}" data-scope="{scope_key}"',
            html,
        )

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
        self.assertIn("Most Edited Files in This Project", html)
        self.assertIn("src/main.py", html)
        self.assertEqual(impact[0].to_dict()["path"], "src/main.py")

    def test_an_unrecognized_edit_action_does_not_break_the_dashboard(self) -> None:
        # File impact is built unconditionally for every window, so indexing the
        # action name directly made any new vocabulary a crash that took down the
        # entire dashboard. An unknown action is counted and shown in none of the
        # three columns, which is visibly a lower total rather than an error.
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        base = _details(self.paths, 7, now=now)[0]
        renamed = replace(
            base,
            file_edits=(
                FileEdit(path="src/main.py", action="refactored", insertions=4, deletions=2),
            ),
        )
        impact = summarize_files_from_details([renamed])
        self.assertEqual(len(impact), 1)
        self.assertEqual(impact[0].edits, 1)
        self.assertEqual(impact[0].updated, 0)
        self.assertEqual((impact[0].insertions, impact[0].deletions), (4, 2))
        dashboard = _build_dashboard(self.paths, now=now)
        self.assertIn("Most Edited Files in This Project", format_dashboard_html(dashboard))

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
        _, edits, _calls = _read_rollout(rollout)
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

    def _write_claude_transcript(self, usage: dict) -> Path:
        root = Path(self.tmpdir.name) / "claude-projects"
        project_dir = root / "-tmp-claude"
        project_dir.mkdir(parents=True, exist_ok=True)
        events = [
            {"timestamp": "2026-04-03T13:17:23.324Z", "type": "user", "cwd": "/tmp/claude", "message": {"role": "user", "content": "hi"}},
            {
                "timestamp": "2026-04-03T13:17:25.324Z",
                "type": "assistant",
                "cwd": "/tmp/claude",
                "message": {"model": "claude-opus-4", "content": [], "usage": usage},
            },
        ]
        (project_dir / "conv1.jsonl").write_text(
            "\n".join(json.dumps(event) for event in events), encoding="utf-8"
        )
        return root

    def test_cache_ratio_stays_bounded_for_both_provider_conventions(self) -> None:
        codex_detail = get_session_details(self.paths, get_session(self.paths))
        self.assertEqual(codex_detail.token_accounting, CACHED_WITHIN_INPUT)
        codex_split = codex_detail.token_split()
        self.assertEqual(codex_split.fresh_input, 200)
        self.assertEqual(codex_split.cached_read, 50)
        self.assertEqual(codex_split.cache_write, 0)
        self.assertEqual(codex_split.output, 30)
        self.assertAlmostEqual(codex_split.cache_ratio() or 0.0, 50 / 250)

        # Anthropic reports cache reads outside input_tokens, so a naive
        # cached/input ratio exceeds 1.0 and previously rendered as 1511%.
        projects_dir = self._write_claude_transcript(
            {
                "input_tokens": 15,
                "output_tokens": 5,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 40,
            }
        )
        claude_detail = _ingest_claude(projects_dir)[0]
        self.assertEqual(claude_detail.token_accounting, CACHED_SEPARATE)
        claude_split = claude_detail.token_split()
        self.assertEqual(claude_split.fresh_input, 15)
        self.assertEqual(claude_split.cached_read, 900)
        self.assertEqual(claude_split.cache_write, 40)
        self.assertEqual(claude_split.output, 5)
        self.assertAlmostEqual(claude_split.cache_ratio() or 0.0, 900 / 915)
        self.assertLessEqual(claude_split.cache_ratio() or 0.0, 1.0)

    def test_cache_write_tokens_are_not_discarded(self) -> None:
        projects_dir = self._write_claude_transcript(
            {
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 33,
            }
        )
        detail = _ingest_claude(projects_dir)[0]
        self.assertEqual(detail.cache_creation_tokens(), 33)
        self.assertEqual(detail.token_split().total, 145)

    def test_canonical_split_reconciles_with_provider_total(self) -> None:
        for detail in [get_session_details(self.paths, get_session(self.paths))]:
            self.assertEqual(detail.token_split().total, detail.effective_total_tokens())
        projects_dir = self._write_claude_transcript(
            {
                "input_tokens": 15,
                "output_tokens": 5,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 40,
            }
        )
        for detail in _ingest_claude(projects_dir):
            self.assertEqual(detail.token_split().total, detail.effective_total_tokens())

    def test_summary_cache_ratio_is_bounded_and_splits_components(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        summary = summarize_details("all", _details(self.paths, 7, now=now))
        self.assertIsNotNone(summary.cache_ratio)
        assert summary.cache_ratio is not None
        self.assertGreaterEqual(summary.cache_ratio, 0.0)
        self.assertLessEqual(summary.cache_ratio, 1.0)
        self.assertEqual(summary.fresh_input_tokens, 200)
        self.assertEqual(summary.cache_read_tokens, 50)
        self.assertEqual(summary.cache_write_tokens, 0)
        self.assertEqual(summary.fresh_input_tokens + summary.cache_read_tokens, summary.input_tokens)

    def test_mixed_convention_sessions_do_not_exceed_one(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        codex_detail = get_session_details(self.paths, get_session(self.paths))
        projects_dir = self._write_claude_transcript(
            {"input_tokens": 15, "output_tokens": 5, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 40}
        )
        claude_detail = _ingest_claude(projects_dir)[0]
        mixed = summarize_details("mixed", [codex_detail, claude_detail])
        self.assertIsNotNone(mixed.cache_ratio)
        assert mixed.cache_ratio is not None
        self.assertLessEqual(mixed.cache_ratio, 1.0)
        self.assertEqual(mixed.cache_read_tokens, 950)
        self.assertEqual(mixed.cache_write_tokens, 40)
        self.assertEqual(mixed.fresh_input_tokens, 215)

    def test_component_pricing_beats_flat_rate_on_cache_heavy_usage(self) -> None:
        detail = replace(
            get_session_details(self.paths, get_session(self.paths)),
            input_tokens=1_000_000,
            cached_input_tokens=900_000,
            output_tokens=10_000,
            reasoning_output_tokens=0,
            total_tokens_from_rollout=1_010_000,
        )
        pricing = PricingConfig(default_usd_per_1k_tokens=0.01)
        flat = round(detail.effective_total_tokens() / 1000.0 * 0.01, 4)
        component = estimate_detail_cost(detail, pricing)
        self.assertLess(component, flat)
        self.assertGreater(component, 0.0)

    def test_recorded_cost_beats_estimated_cost(self) -> None:
        detail = replace(
            get_session_details(self.paths, get_session(self.paths)),
            recorded_cost_usd=7.77,
        )
        self.assertEqual(estimate_detail_cost(detail, PricingConfig()), 7.77)

    def test_unrated_models_are_counted(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        summary = summarize_details("all", _details(self.paths, 7, now=now))
        self.assertEqual(summary.unrated_sessions, 0)
        aliased = replace(
            get_session_details(self.paths, get_session(self.paths)),
            session=replace(get_session(self.paths), model="mystery-alias"),
        )
        self.assertEqual(summarize_details("x", [aliased]).unrated_sessions, 1)

    def test_recorded_zero_cost_is_estimated_and_flagged(self) -> None:
        # A tool that reports cost = 0 has given no usable figure, so the session is
        # estimated and must be reported as unrated rather than counted as rated.
        detail = replace(
            get_session_details(self.paths, get_session(self.paths)),
            session=replace(get_session(self.paths), model="mystery-alias"),
            recorded_cost_usd=0.0,
        )
        self.assertFalse(uses_recorded_cost(detail))
        self.assertGreater(estimate_detail_cost(detail, PricingConfig()), 0.0)
        self.assertEqual(summarize_details("x", [detail]).unrated_sessions, 1)

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


class HistoryBoundTestCase(unittest.TestCase):
    """The bounded history read.

    Three properties matter and are easy to regress independently: the read is
    actually capped, it keeps the *newest* sessions (so the Today/7d/30d windows
    stay exact), and the dashboard admits to the cut rather than presenting a
    truncated history as if it were the whole story.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _isolate_sources(self, root)
        codex_home = root / "codex"
        (codex_home / "sessions").mkdir(parents=True)
        self.codex_home = codex_home
        self.state_db = codex_home / "state_5.sqlite"
        self.paths = Paths(
            codex_home=codex_home,
            state_db=self.state_db,
            sessions_dir=codex_home / "sessions",
            config_dir=codex_home / "config",
            config_file=codex_home / "config" / "config.toml",
            output_dir=codex_home / "cache",
            dashboard_file=codex_home / "cache" / "dashboard.html",
        )
        self.addCleanup(os.environ.pop, ENV_MAX_SESSIONS, None)
        os.environ.pop(ENV_MAX_SESSIONS, None)

    def _seed(self, count: int, step: timedelta = timedelta(hours=1)) -> None:
        """Seed `count` sessions where session 0 is the newest, one `step` apart."""
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
        now = datetime(2026, 4, 10, 12, tzinfo=UTC)
        rows = []
        for index in range(count):
            when = now - step * index
            rollout_path = self.codex_home / "sessions" / f"rollout-{index}.jsonl"
            rollout_path.write_text(
                json.dumps(
                    {
                        "timestamp": when.isoformat(),
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 100,
                                    "output_tokens": 50,
                                    "cached_input_tokens": 0,
                                    "cache_creation_input_tokens": 0,
                                    "reasoning_output_tokens": 0,
                                    "total_tokens": 150,
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            stamp = int(when.timestamp())
            rows.append(
                (
                    f"t{index}",
                    str(rollout_path),
                    stamp,
                    stamp,
                    "codex",
                    "openai",
                    "/proj",
                    f"Session {index}",
                    "workspace",
                    "on-request",
                    150,
                    "gpt-5",
                )
            )
        connection.executemany(
            "INSERT INTO threads (id, rollout_path, created_at, updated_at, source,"
            " model_provider, cwd, title, sandbox_policy, approval_mode, tokens_used, model)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        connection.commit()
        connection.close()

    def test_resolve_max_sessions_defaults_and_parses_env(self) -> None:
        self.assertEqual(resolve_max_sessions(), DEFAULT_MAX_SESSIONS)
        os.environ[ENV_MAX_SESSIONS] = "25"
        self.assertEqual(resolve_max_sessions(), 25)
        # 0 and negatives mean "read everything", not "read nothing".
        os.environ[ENV_MAX_SESSIONS] = "0"
        self.assertEqual(resolve_max_sessions(), 0)
        os.environ[ENV_MAX_SESSIONS] = "-5"
        self.assertEqual(resolve_max_sessions(), 0)
        # Junk falls back to the default rather than reading nothing.
        os.environ[ENV_MAX_SESSIONS] = "banana"
        self.assertEqual(resolve_max_sessions(), DEFAULT_MAX_SESSIONS)
        os.environ[ENV_MAX_SESSIONS] = ""
        self.assertEqual(resolve_max_sessions(), DEFAULT_MAX_SESSIONS)

    def test_iter_sessions_keeps_the_newest_sessions_only(self) -> None:
        self._seed(count=10)
        os.environ[ENV_MAX_SESSIONS] = "4"
        sessions = list(iter_session_details(self.paths))
        self.assertEqual(
            [detail.session.session_id for detail in sessions],
            ["t0", "t1", "t2", "t3"],
            "the cap must drop the oldest sessions and keep the newest",
        )

    def test_iter_sessions_reads_everything_when_unbounded(self) -> None:
        self._seed(count=6)
        os.environ[ENV_MAX_SESSIONS] = "0"
        sessions = list(iter_session_details(self.paths))
        self.assertEqual(len(sessions), 6)

    def test_coverage_reports_what_was_read_against_what_exists(self) -> None:
        self._seed(count=10)
        self.assertEqual(codex_session_coverage(self.paths), (10, 10))
        os.environ[ENV_MAX_SESSIONS] = "3"
        self.assertEqual(codex_session_coverage(self.paths), (3, 10))
        os.environ[ENV_MAX_SESSIONS] = "0"
        self.assertEqual(codex_session_coverage(self.paths), (10, 10))

    def test_dashboard_stays_quiet_when_nothing_is_dropped(self) -> None:
        self._seed(count=4)
        dashboard = _build_dashboard(self.paths, now=datetime(2026, 4, 10, 12, tzinfo=UTC))
        self.assertIsNone(dashboard.coverage_note)
        self.assertNotIn("Partial history", format_dashboard_html(dashboard))

    def test_dashboard_discloses_the_cut_when_history_is_truncated(self) -> None:
        self._seed(count=9)
        os.environ[ENV_MAX_SESSIONS] = "4"
        dashboard = _build_dashboard(self.paths, now=datetime(2026, 4, 10, 12, tzinfo=UTC))
        self.assertIsNotNone(dashboard.coverage_note)
        assert dashboard.coverage_note is not None
        # Named per source, because a blended total cannot tell the reader which of
        # their own tools was truncated.
        self.assertIn("Codex kept 4 of 9", dashboard.coverage_note)
        self.assertIn(ENV_MAX_SESSIONS, dashboard.coverage_note)
        html = format_dashboard_html(dashboard)
        # Rendered once, above the tabs, so it qualifies every number on the page
        # instead of scrolling away with whichever hero is open.
        self.assertIn("Partial history", html)
        self.assertEqual(html.count("Partial history"), 1)
        self.assertLess(
            html.index("Partial history"),
            html.index('class="toolbar"'),
            "the note must sit above the tabs and the metrics they switch between",
        )

    def test_truncated_dashboard_keeps_recent_windows_exact(self) -> None:
        """Newest-first capping is what protects the recent windows.

        One session per day, capped at the newest 3, so the cap only reaches back
        further than a week. Today must be identical either way; the wider
        windows legitimately shrink, which is why the note has to disclose it.
        """
        self._seed(count=12, step=timedelta(days=1))
        now = datetime(2026, 4, 10, 12, tzinfo=UTC)
        os.environ[ENV_MAX_SESSIONS] = "3"
        truncated = _build_dashboard(self.paths, now=now)
        os.environ[ENV_MAX_SESSIONS] = "0"
        full = _build_dashboard(self.paths, now=now)

        def by_key(dashboard: DashboardData, key: str):
            return next(
                window
                for scope in dashboard.scopes
                for window in scope.windows
                if window.key == key and scope.key == "overview"
            )

        self.assertEqual(
            by_key(truncated, "day").summary,
            by_key(full, "day").summary,
            "today is covered by the newest sessions and must not change",
        )
        self.assertEqual(
            by_key(truncated, "day").daily_points,
            by_key(full, "day").daily_points,
        )
        for key in ("week", "month", "all"):
            with self.subTest(window=key):
                self.assertNotEqual(
                    by_key(truncated, key).summary,
                    by_key(full, key).summary,
                    f"a session-count cap can cut into {key}; the note must disclose that",
                )
        self.assertIsNotNone(truncated.coverage_note)


class NonCodexHistoryBoundTestCase(unittest.TestCase):
    """OpenCode and Hermes must obey the same session cap Codex does.

    Both used to read their whole history on every launch while the README
    claimed all four sources were capped. That is the worst combination: the
    docs promise a bound that does not exist, and a user with a long history
    pays for it in startup time. Each source is checked for the two properties
    that matter separately, that the read is capped and that it keeps the newest.
    """

    OPENCODE_COLUMNS = (
        "id, directory, model, cost, tokens_input, tokens_output, tokens_reasoning, "
        "tokens_cache_read, tokens_cache_write, time_created, time_updated"
    )
    HERMES_COLUMNS = (
        "id, cwd, git_branch, git_repo_root, model, message_count, input_tokens, "
        "output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, "
        "estimated_cost_usd, started_at, ended_at, last_activity_at, display_name, title"
    )

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _isolate_sources(self, root)
        previous = os.environ.get(ENV_MAX_SESSIONS)
        self.addCleanup(os.environ.pop, ENV_MAX_SESSIONS, None)
        if previous is not None:
            self.addCleanup(os.environ.__setitem__, ENV_MAX_SESSIONS, previous)
        os.environ.pop(ENV_MAX_SESSIONS, None)
        self.root = root

    def _opencode_db(self, count: int) -> Path:
        db_path = self.root / "opencode.db"
        connection = sqlite3.connect(db_path)
        try:
            connection.execute(f"CREATE TABLE session ({self.OPENCODE_COLUMNS})")
            connection.execute(
                "CREATE TABLE message (id INTEGER PRIMARY KEY, session_id TEXT, data TEXT)"
            )
            connection.execute("CREATE TABLE part (id INTEGER PRIMARY KEY, session_id TEXT, data TEXT)")
            # Oldest first on the way in, so ordering has to come from the query
            # rather than from insertion order.
            rows = [
                (
                    f"s{index}",
                    "/repos/alpha",
                    None,
                    0.1,
                    10,
                    5,
                    0,
                    0,
                    0,
                    1_700_000_000 + index * 60,
                    1_700_000_000 + index * 60,
                )
                for index in range(count)
            ]
            connection.executemany(f"INSERT INTO session VALUES ({', '.join('?' * len(rows[0]))})", rows)
            connection.commit()
        finally:
            connection.close()
        return db_path

    def _hermes_db(self, count: int) -> Path:
        state_db = self.root / "state.db"
        connection = sqlite3.connect(state_db)
        try:
            connection.execute(f"CREATE TABLE sessions ({self.HERMES_COLUMNS})")
            connection.execute(
                "CREATE TABLE messages (session_id TEXT, tool_calls TEXT, tool_call_id TEXT, effect_disposition TEXT)"
            )
            rows = [
                (
                    f"s{index}",
                    "/repos/alpha",
                    None,
                    None,
                    "gpt-5.4",
                    2,
                    10,
                    5,
                    0,
                    0,
                    0,
                    0.1,
                    1_700_000_000 + index * 60,
                    1_700_000_600 + index * 60,
                    1_700_000_600 + index * 60,
                    "alpha",
                    None,
                )
                for index in range(count)
            ]
            connection.executemany(f"INSERT INTO sessions VALUES ({', '.join('?' * len(rows[0]))})", rows)
            connection.commit()
        finally:
            connection.close()
        return state_db

    def test_opencode_read_is_capped_and_keeps_the_newest(self) -> None:
        db_path = self._opencode_db(count=9)
        self.assertEqual(len(_ingest_opencode(db_path)), 9)
        os.environ[ENV_MAX_SESSIONS] = "4"
        capped = _ingest_opencode(db_path)
        self.assertEqual(len(capped), 4)
        newest = max(range(9), key=lambda index: 1_700_000_000 + index * 60)
        self.assertEqual(capped[0].session.session_id, f"s{newest}")

    def test_hermes_read_is_capped_and_keeps_the_newest(self) -> None:
        state_db = self._hermes_db(count=9)
        self.assertEqual(len(_ingest_hermes(state_db)), 9)
        os.environ[ENV_MAX_SESSIONS] = "4"
        capped = _ingest_hermes(state_db)
        self.assertEqual(len(capped), 4)
        newest = max(range(9), key=lambda index: 1_700_000_000 + index * 60)
        self.assertEqual(capped[0].session.session_id, f"s{newest}")

    def test_every_source_reports_its_own_coverage(self) -> None:
        self._opencode_db(count=9)
        self._hermes_db(count=7)
        os.environ["CODEX_STATS_OPENCODE_HOME"] = str(self.root)
        os.environ["CODEX_STATS_HERMES_HOME"] = str(self.root)
        os.environ["CODEX_HOME"] = str(self.root / "no-codex")
        os.environ[ENV_MAX_SESSIONS] = "4"
        reported = {source.key: source.coverage() for source in iter_sources()}
        self.assertEqual(reported["opencode"], (4, 9))
        self.assertEqual(reported["hermes"], (4, 7))
        self.assertEqual(reported["codex"], (0, 0))
        self.assertEqual(reported["claude"], (0, 0))

    def test_coverage_counts_everything_when_unbounded(self) -> None:
        self._opencode_db(count=6)
        os.environ["CODEX_STATS_OPENCODE_HOME"] = str(self.root)
        os.environ[ENV_MAX_SESSIONS] = "0"
        reported = {source.key: source.coverage() for source in iter_sources()}
        self.assertEqual(reported["opencode"], (6, 6))

    def test_coverage_stays_silent_rather_than_claiming_a_whole_history(self) -> None:
        # A database whose schema drifted cannot be counted. The note is disclosure,
        # so an uncountable source must say nothing instead of asserting that the
        # history it read is the whole history.
        broken = self.root / "opencode.db"
        connection = sqlite3.connect(broken)
        try:
            connection.execute("CREATE TABLE something_else (id INTEGER)")
            connection.commit()
        finally:
            connection.close()
        os.environ["CODEX_STATS_OPENCODE_HOME"] = str(self.root)
        os.environ["CODEX_HOME"] = str(self.root / "no-codex")
        os.environ[ENV_MAX_SESSIONS] = "2"
        source = next(s for s in iter_sources() if s.key == "opencode")
        self.assertEqual(source.coverage(), (0, 0))
        dashboard = _build_dashboard(Paths.discover())
        self.assertIsNone(dashboard.coverage_note)

    def test_a_drifted_schema_costs_one_source_rather_than_the_dashboard(self) -> None:
        # The four tabs exist whatever the data says, so an unreadable source has to
        # degrade to its empty state. Before this was handled, one drifted schema
        # raised out of ingest and took the other three down with it.
        broken = self.root / "opencode.db"
        connection = sqlite3.connect(broken)
        try:
            connection.execute("CREATE TABLE something_else (id INTEGER)")
            connection.commit()
        finally:
            connection.close()
        os.environ["CODEX_STATS_OPENCODE_HOME"] = str(self.root)
        os.environ["CODEX_HOME"] = str(self.root / "no-codex")
        dashboard = _build_dashboard(Paths.discover())
        keys = {scope.key for scope in dashboard.scopes}
        self.assertEqual(keys, {"overview", "codex", "opencode", "claude", "hermes"})
        html = format_dashboard_html(dashboard)
        self.assertIn("OpenCode", html)


EFFICIENCY_NOW = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)


def efficiency_detail(
    *,
    session_id: str,
    source: str = "codex",
    cost_usd: float | None = 10.0,
    edits: tuple[tuple[str, int, int], ...] = (),
) -> SessionDetails:
    """A session with a known cost and a known set of (path, insertions, deletions)."""
    created = EFFICIENCY_NOW - timedelta(days=1)
    session = SessionRecord(
        session_id=session_id,
        created_at=created,
        updated_at=created,
        cwd="/tmp/project",
        model="gpt-5.4",
        model_provider="openai",
        tokens_used=1000,
        rollout_path=Path("/tmp/rollout.jsonl"),
        git_branch=None,
        git_origin_url=None,
        source=source,
    )
    return SessionDetails(
        session=session,
        request_count=3,
        input_tokens=100,
        output_tokens=50,
        cached_input_tokens=0,
        reasoning_output_tokens=0,
        total_tokens_from_rollout=150,
        started_at=created,
        recorded_cost_usd=cost_usd,
        token_accounting=CACHED_SEPARATE,
        file_edits=tuple(
            FileEdit(path=path, action="updated", insertions=insertions, deletions=deletions)
            for path, insertions, deletions in edits
        ),
    )


class EfficiencyTest(unittest.TestCase):
    """Spend joined to the edits recorded in the same sessions.

    The load-bearing property is the split between sources that record file edits
    and sources that do not. Getting it wrong does not produce a wrong-looking
    number, it produces a confidently wrong ranking that names an unmeasurable
    tool as the expensive one, so most of these tests are about what stays None.
    """

    def test_cost_per_line_joins_spend_to_recorded_edits(self) -> None:
        summary = summarize_efficiency_from_details(
            [efficiency_detail(session_id="a", cost_usd=20.0, edits=(("/a.py", 500, 100),))]
        )
        self.assertTrue(summary.tracked)
        self.assertEqual(summary.lines_changed, 600)
        self.assertEqual(summary.files_touched, 1)
        # $20 over 600 changed lines is $33.33 per 1k.
        self.assertAlmostEqual(summary.cost_per_1k_lines or 0, 20.0 / 0.6, places=4)
        self.assertEqual(summary.cost_per_file, 20.0)
        self.assertEqual(summary.cost_per_editing_session, 20.0)

    def test_editing_and_read_only_sessions_are_separated(self) -> None:
        summary = summarize_efficiency_from_details(
            [
                efficiency_detail(session_id="edit", cost_usd=10.0, edits=(("/a.py", 100, 0),)),
                efficiency_detail(session_id="ro1", cost_usd=5.0, edits=()),
                efficiency_detail(session_id="ro2", cost_usd=5.0, edits=()),
            ]
        )
        self.assertEqual(summary.editing_sessions, 1)
        self.assertEqual(summary.read_only_sessions, 2)
        self.assertEqual(summary.read_only_cost_usd, 10.0)
        self.assertAlmostEqual(summary.read_only_cost_share or 0, 0.5, places=6)

    def test_a_source_that_records_no_edits_is_not_reported_as_read_only(self) -> None:
        # OpenCode and Hermes store cost and tokens but not files. Counting their
        # sessions as read-only would invent a finding; the only honest statement
        # is that the window has nothing to divide.
        summary = summarize_efficiency_from_details(
            [efficiency_detail(session_id="o", source="opencode", cost_usd=5.0)]
        )
        self.assertFalse(summary.tracked)
        self.assertEqual(summary.untracked_sources, ("OpenCode",))
        self.assertEqual(summary.untracked_cost_usd, 5.0)
        self.assertIsNone(summary.cost_per_1k_lines)
        self.assertIsNone(summary.read_only_cost_share)

    def test_untracked_spend_stays_out_of_the_ratios(self) -> None:
        summary = summarize_efficiency_from_details(
            [
                efficiency_detail(session_id="a", cost_usd=10.0, edits=(("/a.py", 1000, 0),)),
                efficiency_detail(session_id="o", source="opencode", cost_usd=500.0),
            ]
        )
        self.assertTrue(summary.tracked)
        # Only the tracked $10 is divided, not the blended $510.
        self.assertEqual(summary.tracked_cost_usd, 10.0)
        self.assertEqual(summary.untracked_cost_usd, 500.0)
        self.assertAlmostEqual(summary.cost_per_1k_lines or 0, 10.0, places=6)

    def test_no_recorded_edits_leaves_ratios_unset_rather_than_zero(self) -> None:
        summary = summarize_efficiency_from_details(
            [efficiency_detail(session_id="a", cost_usd=10.0, edits=())]
        )
        self.assertTrue(summary.tracked)
        self.assertEqual(summary.lines_changed, 0)
        self.assertIsNone(summary.cost_per_1k_lines)
        self.assertIsNone(summary.cost_per_file)
        self.assertIsNone(summary.cost_per_editing_session)
        self.assertIsNone(summary.rework_ratio)

    def test_rework_ratio_and_net_shrinkage(self) -> None:
        summary = summarize_efficiency_from_details(
            [
                efficiency_detail(
                    session_id="a",
                    edits=(("/grow.py", 300, 100), ("/shrink.py", 40, 90)),
                )
            ]
        )
        # 190 removed against 340 added.
        self.assertAlmostEqual(summary.rework_ratio or 0, 190 / 340, places=6)
        self.assertEqual(summary.churn_files, 1)
        self.assertEqual(summary.insertions, 340)
        self.assertEqual(summary.deletions, 190)

    def test_hotspots_rank_by_sessions_and_span_projects(self) -> None:
        summary = summarize_efficiency_from_details(
            [
                efficiency_detail(session_id="a", edits=(("/hot.py", 10, 0), ("/once.py", 5, 0))),
                efficiency_detail(session_id="b", edits=(("/hot.py", 10, 40), ("/once.py", 5, 0))),
                efficiency_detail(session_id="c", edits=(("/hot.py", 10, 0),)),
                efficiency_detail(session_id="d", edits=(("/hot.py", 1, 0),)),
            ]
        )
        paths = [entry.path for entry in summary.hotspots]
        self.assertEqual(paths, ["/hot.py", "/once.py"])
        # Ranked by how many separate sessions rewrote the file.
        self.assertEqual(summary.hotspots[1].sessions, 2)
        hot = summary.hotspots[0]
        self.assertEqual(hot.sessions, 4)
        self.assertEqual(hot.edits, 4)
        self.assertEqual(hot.net_lines, -9)

    def test_a_file_touched_once_and_growing_is_not_a_hotspot(self) -> None:
        # One session that added lines is a file that was edited, not one that
        # resisted anything, so it must not appear as a problem to fix.
        summary = summarize_efficiency_from_details(
            [efficiency_detail(session_id="a", edits=(("/fine.py", 20, 0),))]
        )
        self.assertEqual(summary.hotspots, [])

    def test_a_singly_touched_shrinking_file_still_counts_as_churn(self) -> None:
        summary = summarize_efficiency_from_details(
            [efficiency_detail(session_id="a", edits=(("/pruned.py", 2, 50),))]
        )
        self.assertEqual([entry.path for entry in summary.hotspots], ["/pruned.py"])
        self.assertEqual(summary.churn_files, 1)

    def test_serializes_read_only_share_and_hotspot_net(self) -> None:
        summary = summarize_efficiency_from_details(
            [
                efficiency_detail(session_id="a", cost_usd=10.0, edits=(("/a.py", 100, 20),)),
                efficiency_detail(session_id="b", cost_usd=10.0, edits=(("/a.py", 0, 0),)),
            ]
        )
        payload = summary.to_dict()
        self.assertIn("read_only_cost_share", payload)
        self.assertEqual(payload["hotspots"][0]["net_lines"], 80)


class ToolEfficiencyTest(unittest.TestCase):
    """The per-tool comparison behind "which of my agents is worth it".

    Every tool stays in the result. A tool that records no file edits carries its
    spend and a None ratio, because dropping it would turn "cannot be measured"
    into "not in the comparison" and quietly reduce the table to a cost ranking.
    """

    def test_every_tool_appears_with_its_own_measurement(self) -> None:
        entries = summarize_tool_efficiency_from_details(
            [
                efficiency_detail(session_id="c1", source="codex", cost_usd=10.0, edits=(("/a.py", 1000, 0),)),
                efficiency_detail(session_id="o1", source="opencode", cost_usd=99.0),
            ]
        )
        by_source = {entry.source: entry for entry in entries}
        self.assertEqual(set(by_source), {"codex", "opencode"})
        self.assertTrue(by_source["codex"].tracks_file_edits)
        self.assertAlmostEqual(by_source["codex"].cost_per_1k_lines or 0, 10.0, places=6)
        self.assertFalse(by_source["opencode"].tracks_file_edits)
        self.assertIsNone(by_source["opencode"].cost_per_1k_lines)
        # The unmeasurable tool still carries its spend.
        self.assertEqual(by_source["opencode"].estimated_cost_usd, 99.0)

    def test_ranked_by_spend_so_the_biggest_stake_reads_first(self) -> None:
        entries = summarize_tool_efficiency_from_details(
            [
                efficiency_detail(session_id="c", source="codex", cost_usd=10.0),
                efficiency_detail(session_id="h", source="hermes", cost_usd=50.0),
            ]
        )
        self.assertEqual([entry.source for entry in entries], ["hermes", "codex"])

    def test_empty_input_is_an_empty_list_not_an_error(self) -> None:
        self.assertEqual(summarize_tool_efficiency_from_details([]), [])


class EfficiencyTakeawayTest(unittest.TestCase):
    def test_states_the_cost_of_the_work_when_there_was_work(self) -> None:
        lines = summarize_efficiency_takeaways(
            summarize_efficiency_from_details(
                [efficiency_detail(session_id="a", cost_usd=20.0, edits=(("/a.py", 1000, 0),))]
            )
        )
        self.assertTrue(any("per 1k lines changed" in line for line in lines))

    def test_says_nothing_when_the_window_tracks_no_edits(self) -> None:
        self.assertEqual(
            summarize_efficiency_takeaways(
                summarize_efficiency_from_details(
                    [efficiency_detail(session_id="o", source="opencode", cost_usd=5.0)]
                )
            ),
            [],
        )

    def test_flags_spend_that_bought_no_edits(self) -> None:
        lines = summarize_efficiency_takeaways(
            summarize_efficiency_from_details(
                [
                    efficiency_detail(session_id="e", cost_usd=10.0, edits=(("/a.py", 500, 0),)),
                    efficiency_detail(session_id="r", cost_usd=90.0, edits=()),
                ]
            )
        )
        self.assertTrue(any("changed no files" in line for line in lines))

    def test_flags_heavy_rework(self) -> None:
        lines = summarize_efficiency_takeaways(
            summarize_efficiency_from_details(
                [efficiency_detail(session_id="a", edits=(("/a.py", 100, 400),))]
            )
        )
        self.assertTrue(any("Rework is high" in line for line in lines))

    def test_stays_quiet_on_a_healthy_window(self) -> None:
        lines = summarize_efficiency_takeaways(
            summarize_efficiency_from_details(
                [efficiency_detail(session_id="a", cost_usd=10.0, edits=(("/a.py", 1000, 10),))]
            )
        )
        self.assertEqual([line for line in lines if "Rework is high" in line], [])
        self.assertEqual([line for line in lines if "changed no files" in line], [])


BRANCH_NOW = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)


def branch_detail(
    *,
    session_id: str,
    branch: str | None,
    project: str = "alpha",
    model: str = "gpt-5.4",
    model_provider: str = "openai",
    days_ago: int = 0,
    total_tokens: int = 10_000,
    reasoning_tokens: int = 0,
) -> SessionDetails:
    created = BRANCH_NOW - timedelta(days=days_ago)
    return SessionDetails(
        session=SessionRecord(
            session_id=session_id,
            created_at=created,
            updated_at=created,
            cwd=f"/tmp/{project}",
            model=model,
            model_provider=model_provider,
            tokens_used=total_tokens,
            rollout_path=Path("/tmp/rollout.jsonl"),
            git_branch=branch,
            git_origin_url=None,
        ),
        request_count=4,
        input_tokens=total_tokens // 2,
        output_tokens=total_tokens // 4,
        cached_input_tokens=0,
        reasoning_output_tokens=reasoning_tokens,
        total_tokens_from_rollout=total_tokens,
        started_at=created,
        token_accounting=CACHED_SEPARATE,
    )


class ModelVendorTest(unittest.TestCase):
    def test_resolves_vendor_from_model_name(self) -> None:
        self.assertEqual(model_vendor("gpt-5.4", "openai"), "OpenAI")
        self.assertEqual(model_vendor("gpt-5.1-codex-mini", "openai"), "OpenAI")
        self.assertEqual(model_vendor("o3-mini", "openai"), "OpenAI")
        self.assertEqual(model_vendor("claude-opus-5", "anthropic"), "Anthropic")
        self.assertEqual(model_vendor("gemini-3-pro", "google"), "Google")

    def test_strips_vendor_prefix_before_matching(self) -> None:
        # Hermes and Claude Code write a prefixed name where Codex writes a bare one.
        # Both must resolve to the same vendor or cross-tool spend splits in two.
        self.assertEqual(model_vendor("anthropic/claude-opus-4.6", "hermes"), "Anthropic")
        self.assertEqual(model_vendor("claude-opus-4.6", "anthropic"), "Anthropic")

    def test_falls_back_to_provider_for_codenames(self) -> None:
        # Claude Code records codenames, but the provider beside them is a real vendor.
        self.assertEqual(model_vendor("blue-otter", "anthropic"), "Anthropic")
        self.assertEqual(model_vendor("red-panda", "anthropic"), "Anthropic")

    def test_router_provider_is_not_treated_as_a_vendor(self) -> None:
        # "opencode" and "hermes" name the CLI, not whoever it routes to, so a codename
        # beside one of them stays unattributed rather than claiming a wrong vendor.
        self.assertEqual(model_vendor("big-pickle", "opencode"), UNIDENTIFIED_VENDOR_LABEL)
        self.assertEqual(model_vendor(None, "hermes"), UNIDENTIFIED_VENDOR_LABEL)

    def test_missing_model_and_provider(self) -> None:
        self.assertEqual(model_vendor(None, None), UNIDENTIFIED_VENDOR_LABEL)
        self.assertEqual(model_vendor("", ""), UNIDENTIFIED_VENDOR_LABEL)


class ProviderBreakdownTest(unittest.TestCase):
    def test_groups_spend_by_vendor(self) -> None:
        details = [
            branch_detail(session_id="a", branch="main", model="gpt-5.4", model_provider="openai"),
            branch_detail(session_id="b", branch="main", model="gpt-5.5", model_provider="openai"),
            branch_detail(session_id="c", branch="main", model="claude-opus-5", model_provider="anthropic"),
        ]
        entries = summarize_providers_from_details(details)
        self.assertEqual([entry.name for entry in entries], ["OpenAI", "Anthropic"])
        self.assertEqual(entries[0].sessions, 2)
        self.assertEqual(entries[0].total_tokens, 20_000)

    def test_cross_tool_vendor_spellings_collapse(self) -> None:
        details = [
            branch_detail(session_id="a", branch="main", model="gpt-5.4", model_provider="openai"),
            branch_detail(
                session_id="b",
                branch="main",
                model="anthropic/claude-opus-4.6",
                model_provider="hermes",
            ),
        ]
        entries = summarize_providers_from_details(details)
        self.assertEqual(sorted(entry.name for entry in entries), ["Anthropic", "OpenAI"])

    def test_unattributed_spend_is_kept_visible(self) -> None:
        details = [
            branch_detail(session_id="a", branch="main", model="gpt-5.4", model_provider="openai"),
            branch_detail(session_id="b", branch="main", model="big-pickle", model_provider="opencode"),
        ]
        entries = summarize_providers_from_details(details)
        by_name = {entry.name: entry for entry in entries}
        self.assertIn(UNIDENTIFIED_VENDOR_LABEL, by_name)
        # Both cost the same, so the unattributed half must still be reported rather
        # than dropped for being unidentifiable.
        self.assertEqual(by_name[UNIDENTIFIED_VENDOR_LABEL].total_tokens, 10_000)

    def test_empty_input(self) -> None:
        self.assertEqual(summarize_providers_from_details([]), [])


class BranchSummaryTest(unittest.TestCase):
    def test_unsupported_when_no_session_records_a_branch(self) -> None:
        details = [branch_detail(session_id="a", branch=None)]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW)
        self.assertFalse(summary.supported)
        self.assertEqual(summary.branches, [])
        self.assertEqual(summary.total_sessions, 1)

    def test_groups_by_repository_and_branch(self) -> None:
        # The same branch name exists independently in several checkouts, so keying on
        # the name alone would merge unrelated work into one expensive looking branch.
        details = [
            branch_detail(session_id="a", branch="main", project="alpha"),
            branch_detail(session_id="b", branch="main", project="beta"),
        ]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW)
        self.assertTrue(summary.supported)
        self.assertEqual(len(summary.branches), 2)
        self.assertEqual(
            sorted(branch.project_name for branch in summary.branches),
            ["alpha", "beta"],
        )
        self.assertEqual(summary.branches[0].label, "alpha / main")

    def test_aggregates_multiple_sessions_on_one_branch(self) -> None:
        details = [
            branch_detail(session_id="a", branch="feature", total_tokens=10_000),
            branch_detail(session_id="b", branch="feature", total_tokens=30_000),
        ]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW)
        self.assertEqual(len(summary.branches), 1)
        branch = summary.branches[0]
        self.assertEqual(branch.sessions, 2)
        self.assertEqual(branch.total_tokens, 40_000)
        self.assertEqual(branch.tokens_per_session, 20_000)

    def test_ranks_branches_by_cost(self) -> None:
        details = [
            branch_detail(session_id="a", branch="cheap", total_tokens=1_000),
            branch_detail(session_id="b", branch="pricey", total_tokens=90_000),
        ]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW)
        self.assertEqual([branch.name for branch in summary.branches], ["pricey", "cheap"])

    def test_limit_truncates_the_ranked_list(self) -> None:
        details = [
            branch_detail(session_id=f"s{i}", branch=f"b{i}", total_tokens=i * 1_000) for i in range(1, 6)
        ]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW, limit=2)
        self.assertEqual([branch.name for branch in summary.branches], ["b5", "b4"])

    def test_flags_branches_that_went_quiet(self) -> None:
        details = [
            branch_detail(session_id="a", branch="active", days_ago=0, total_tokens=10_000),
            branch_detail(session_id="b", branch="abandoned", days_ago=40, total_tokens=80_000),
        ]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW, idle_days=14)
        self.assertEqual([branch.name for branch in summary.idle_branches], ["abandoned"])
        self.assertEqual(summary.idle_cost_usd, summary.idle_branches[0].estimated_cost_usd)
        self.assertGreaterEqual(summary.idle_branches[0].idle_days, 14)

    def test_no_idle_branches_when_everything_is_recent(self) -> None:
        details = [branch_detail(session_id="a", branch="fresh", days_ago=1)]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW, idle_days=14)
        self.assertEqual(summary.idle_branches, [])
        self.assertEqual(summary.idle_cost_usd, 0.0)

    def test_counts_sessions_without_a_branch(self) -> None:
        details = [
            branch_detail(session_id="a", branch="main"),
            branch_detail(session_id="b", branch=None),
            branch_detail(session_id="c", branch=None),
        ]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW)
        self.assertEqual(summary.tracked_sessions, 1)
        self.assertEqual(summary.total_sessions, 3)
        self.assertEqual(summary.untracked_sessions, 2)

    def test_idle_days_never_go_negative(self) -> None:
        # A session stamped slightly in the future must not report negative idleness.
        details = [branch_detail(session_id="a", branch="main", days_ago=0)]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW - timedelta(days=1))
        self.assertGreaterEqual(summary.branches[0].idle_days, 0)


class BranchTakeawayTest(unittest.TestCase):
    def test_reports_idle_spend(self) -> None:
        details = [
            branch_detail(session_id="a", branch="done", days_ago=0),
            branch_detail(session_id="b", branch="dropped", days_ago=30, total_tokens=50_000),
        ]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW)
        lines = summarize_branch_takeaways(summary)
        self.assertTrue(lines)
        self.assertIn("dropped", lines[0])
        self.assertIn("quiet", lines[0])

    def test_silent_when_unsupported(self) -> None:
        summary = summarize_branches_from_details([branch_detail(session_id="a", branch=None)], now=BRANCH_NOW)
        self.assertEqual(summarize_branch_takeaways(summary), [])

    def test_silent_when_none(self) -> None:
        self.assertEqual(summarize_branch_takeaways(None), [])


class ReasoningShareTest(unittest.TestCase):
    def test_ratio_of_total(self) -> None:
        details = [branch_detail(session_id="a", branch="main", total_tokens=1_000, reasoning_tokens=250)]
        summary = summarize_details("all time", details)
        self.assertEqual(summary.reasoning_output_tokens, 250)
        self.assertAlmostEqual(summary.reasoning_ratio, 0.25)

    def test_none_when_nothing_recorded_reasoning(self) -> None:
        details = [branch_detail(session_id="a", branch="main", reasoning_tokens=0)]
        summary = summarize_details("all time", details)
        self.assertEqual(summary.reasoning_output_tokens, 0)
        self.assertIsNone(summary.reasoning_ratio)

    def test_none_when_there_are_no_tokens_at_all(self) -> None:
        details = [branch_detail(session_id="a", branch="main", total_tokens=0, reasoning_tokens=0)]
        summary = summarize_details("all time", details)
        self.assertIsNone(summary.reasoning_ratio)


class TakeawayPriorityTest(unittest.TestCase):
    """Measured facts have to survive a full list, which is the whole point of them."""

    def _window(self, details: list[SessionDetails]):
        return _build_window(
            key="all",
            label="All Time",
            description="All recorded sessions.",
            current_details=details,
            previous_details=details,
            current_label="all time",
            previous_label="prior",
            trend_days=30,
            all_details=details,
            pricing=None,
            now=BRANCH_NOW,
        )

    def test_branch_facts_survive_a_full_heuristic_list(self) -> None:
        # Heuristic advice easily outnumbers the slots. The measured facts still have
        # to appear, or the list quietly reverts to advice only.
        details = [
            branch_detail(
                session_id=f"s{i}",
                branch="quiet-branch" if i == 0 else "active",
                days_ago=90 if i == 0 else 0,
            )
            for i in range(6)
        ]
        window = self._window(details)
        lines = summarize_takeaways(
            summary=window.summary,
            comparison=window.comparison,
            costs=window.costs,
            insights=window.insights,
            file_impact=window.file_impact,
            behavior=None,
            branches=window.branches,
        )
        self.assertTrue(any("went quiet" in line for line in lines), lines)
        self.assertLessEqual(len(lines), 4)

    def test_behavior_and_branch_lines_alternate(self) -> None:
        # Either measured category can be the longer one, so they are interleaved
        # rather than appended, and a long behavior list cannot crowd branches out.
        behavior = BehaviorSummary(
            total_calls=100,
            error_calls=20,
            repeated_calls=0,
            sessions_with_calls=10,
            abandoned_turns=0,
            read_calls=0,
            edit_calls=0,
            categories=[],
            tools=[],
        )
        details = [
            branch_detail(
                session_id=f"s{i}",
                branch="quiet" if i == 0 else "live",
                days_ago=90 if i == 0 else 0,
            )
            for i in range(6)
        ]
        window = self._window(details)
        lines = summarize_takeaways(
            summary=window.summary,
            comparison=window.comparison,
            costs=window.costs,
            insights=window.insights,
            file_impact=window.file_impact,
            behavior=behavior,
            branches=window.branches,
        )
        quiet_index = next(i for i, line in enumerate(lines) if "went quiet" in line)
        failure_index = next(i for i, line in enumerate(lines) if "failed" in line)
        # Whichever category is longer, the other still lands inside the budget.
        self.assertLess(quiet_index, 4, lines)
        self.assertLess(failure_index, 4, lines)

    def test_heuristics_still_lead_when_there_is_room(self) -> None:
        details = [branch_detail(session_id="a", branch="main")]
        window = self._window(details)
        lines = summarize_takeaways(
            summary=window.summary,
            comparison=window.comparison,
            costs=window.costs,
            insights=window.insights,
            file_impact=window.file_impact,
            behavior=None,
            branches=window.branches,
        )
        # Nothing to promote, so the ordinary advice is returned unchanged.
        self.assertTrue(lines)
        self.assertFalse(any("went quiet" in line for line in lines))

    def test_branch_takeaway_names_the_repository(self) -> None:
        details = [
            branch_detail(session_id="a", branch="main", project="alpha", days_ago=90),
            branch_detail(session_id="b", branch="main", project="beta", days_ago=90),
        ]
        summary = summarize_branches_from_details(details, now=BRANCH_NOW)
        line = summarize_branch_takeaways(summary)[0]
        self.assertIn("alpha / main", line)
        self.assertIn("beta / main", line)


if __name__ == "__main__":
    unittest.main()