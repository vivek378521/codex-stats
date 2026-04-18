from __future__ import annotations

import json
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
from codex_stats.display import (
    format_dashboard_html,
    format_dashboard_svg_assets,
    format_report_html,
    format_report_svg,
    format_report_svg_assets,
    format_watch_dashboard,
)
from codex_stats.ingest import get_session, get_session_details
from codex_stats.metrics import (
    apply_watch_state,
    build_watch_alerts,
    build_report,
    details_for_last_days,
    filter_details_by_project,
    parse_since_days,
    run_doctor,
    summarize_compare,
    summarize_compare_from_details,
    summarize_compare_named,
    summarize_costs,
    summarize_daily,
    summarize_daily_from_details,
    summarize_history,
    summarize_history_from_details,
    summarize_insights,
    summarize_insights_from_details,
    summarize_models,
    summarize_month,
    summarize_project_drilldown,
    summarize_projects,
    summarize_details,
    summarize_today,
    summarize_top_sessions_from_details,
    summarize_top_sessions,
    summarize_week,
)
from codex_stats.models import WatchAlert
from codex_stats.otel import build_otlp_metrics_payload, parse_key_value_pairs, write_otlp_metrics_json
from codex_stats.transfer import export_payload, read_import, read_imports, read_imports_with_summary, write_merged_export
from codex_stats.watch_state import build_watch_scope_key, load_watch_state, save_watch_state


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
            watch_state_file=codex_home / "config" / "watch-state.json",
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
        self.assertGreater(summary.average_session_duration_minutes, 0.0)
        self.assertGreater(summary.tokens_per_minute, 0.0)
        self.assertEqual(summary.longest_active_streak_days, 1)

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
        self.assertIn("Heavy cost concentration in one session", insights.anomalies)
        self.assertIn("Low cache efficiency", insights.anomalies)
        self.assertIn("Split exploratory work into smaller sessions.", insights.recommendations)

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
        merged_with_summary, import_summary = read_imports_with_summary([export_path_a, export_path_b])
        self.assertEqual(len(merged_with_summary), 1)
        self.assertEqual(import_summary.files_read, 2)
        self.assertEqual(import_summary.sessions_loaded, 2)
        self.assertEqual(import_summary.duplicates_removed, 1)

    def test_compare_named_and_report(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        report = summarize_compare_named(self.paths, "today", "yesterday", now=now)
        weekly = build_report(self.paths, "weekly", now=now)
        self.assertEqual(report.current.total_tokens, 280)
        self.assertEqual(report.previous.total_tokens, 0)
        self.assertEqual(weekly.period, "weekly")
        self.assertEqual(weekly.summary.total_tokens, 280)
        self.assertEqual(weekly.comparison.previous.total_tokens, 0)
        self.assertIsNone(weekly.project_name)

    def test_project_drilldown_and_filtered_top(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        summary = summarize_project_drilldown(self.paths, "project", days=30, now=now)
        details = details_for_last_days(self.paths, 30, now=now)
        top = summarize_top_sessions_from_details(details, limit=5, project_name="project")
        self.assertEqual(summary.total_tokens, 280)
        self.assertEqual(summary.requests, 2)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].project_name, "project")

    def test_export_payload_since_and_parser(self) -> None:
        payload = export_payload(self.paths, since="30d")
        self.assertEqual(len(payload["sessions"]), 1)
        self.assertEqual(parse_since_days("30d"), 30)
        with self.assertRaises(ValueError):
            parse_since_days("30")

    def test_project_report_and_merge_export(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        report = build_report(self.paths, "weekly", project_name="project", now=now)
        export_path_a = Path(self.tmpdir.name) / "a.json"
        export_path_b = Path(self.tmpdir.name) / "b.json"
        export_path_out = Path(self.tmpdir.name) / "merged.json"
        export_path_a.write_text(json.dumps(export_payload(self.paths)), encoding="utf-8")
        export_path_b.write_text(json.dumps(export_payload(self.paths)), encoding="utf-8")
        _, import_summary = write_merged_export([export_path_a, export_path_b], export_path_out)
        merged_payload = json.loads(export_path_out.read_text(encoding="utf-8"))
        self.assertEqual(report.project_name, "project")
        self.assertEqual(report.summary.total_tokens, 280)
        self.assertEqual(report.projects, [])
        self.assertEqual(len(merged_payload["sessions"]), 1)
        self.assertEqual(import_summary.merged_sessions, 1)

    def test_otlp_payload_and_write(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        payload = build_otlp_metrics_payload(
            self.paths,
            since="30d",
            daily_days=7,
            service_name="codex-stats-test",
            resource_attributes={"deployment.environment": "test"},
            now=now,
        )
        resource_metrics = payload["resourceMetrics"]
        self.assertEqual(len(resource_metrics), 1)
        scope_metrics = resource_metrics[0]["scopeMetrics"]
        self.assertEqual(len(scope_metrics), 1)
        metrics = scope_metrics[0]["metrics"]
        metric_names = {metric["name"] for metric in metrics}
        self.assertIn("codex_stats_tokens", metric_names)
        self.assertIn("codex_stats_daily_tokens", metric_names)
        self.assertIn("codex_stats_daily_requests", metric_names)
        attributes = resource_metrics[0]["resource"]["attributes"]
        attribute_map = {attribute["key"]: attribute["value"]["stringValue"] for attribute in attributes}
        self.assertEqual(attribute_map["service.name"], "codex-stats-test")
        self.assertEqual(attribute_map["deployment.environment"], "test")
        self.assertEqual(attribute_map["codex.stats.window"], "30d")

        tokens_metric = next(metric for metric in metrics if metric["name"] == "codex_stats_tokens")
        self.assertFalse(tokens_metric["sum"]["isMonotonic"])
        total_point = next(point for point in tokens_metric["sum"]["dataPoints"] if not point["attributes"])
        project_point = next(
            point
            for point in tokens_metric["sum"]["dataPoints"]
            if any(attribute["key"] == "project" and attribute["value"]["stringValue"] == "project" for attribute in point["attributes"])
        )
        self.assertEqual(total_point["asInt"], "280")
        self.assertEqual(project_point["asInt"], "280")

        output_path = Path(self.tmpdir.name) / "otlp-metrics.json"
        write_otlp_metrics_json(self.paths, output_path, since="30d", daily_days=7, now=now)
        written_payload = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(written_payload["resourceMetrics"][0]["scopeMetrics"][0]["scope"]["name"], "codex-stats")

    def test_parse_key_value_pairs(self) -> None:
        pairs = parse_key_value_pairs(["a=1", "b=two"])
        self.assertEqual(pairs, {"a": "1", "b": "two"})
        with self.assertRaises(ValueError):
            parse_key_value_pairs(["broken"])

    def test_watch_dashboard_helpers(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        pricing = None
        current_details = filter_details_by_project(details_for_last_days(self.paths, 7, now=now), "project")
        previous_details = filter_details_by_project(details_for_last_days(self.paths, 7, now=now - timedelta(days=7)), "project")
        summary = summarize_details("last 7 days", current_details)
        compare = summarize_compare_from_details(
            current_details,
            previous_details,
            current_label="last 7 days",
            previous_label="prev 7 days",
            pricing=pricing,
        )
        daily = summarize_daily_from_details(current_details, days=7, now=now)
        history = summarize_history_from_details(current_details, limit=3)
        top = summarize_top_sessions_from_details(current_details, limit=3)
        insights = summarize_insights_from_details(current_details, month=summary, now=now)
        alerts = build_watch_alerts(
            summary,
            compare,
            insights,
            cost_threshold_usd=0.001,
            token_threshold=100,
            request_threshold=1,
            delta_pct_threshold=10.0,
        )
        rendered = format_watch_dashboard(
            summary,
            compare,
            daily,
            top,
            history,
            insights,
            alerts,
            now=now,
            interval_seconds=2.0,
            scope_label="project",
        )
        self.assertIn("Codex Stats Watch [project]", rendered)
        self.assertIn("Press Ctrl-C to stop.", rendered)
        self.assertIn("Daily Usage", rendered)
        self.assertIn("Alerts", rendered)
        self.assertTrue(any(alert.name == "cost_threshold" for alert in alerts))
        self.assertTrue(any(alert.name == "token_threshold" for alert in alerts))

    def test_apply_watch_state_marks_new_alerts_after_baseline(self) -> None:
        session = get_session(self.paths, "session-1")
        assert session is not None
        details = [get_session_details(self.paths, session)]
        baseline_alerts = build_watch_alerts(
            summarize_details("last 7 days", details),
            summarize_compare_from_details(details, [], current_label="last 7 days", previous_label="prev 7 days"),
            summarize_insights_from_details(details, month=summarize_details("last 7 days", details)),
            token_threshold=100,
        )
        alerts, seen_sessions, seen_alerts = apply_watch_state(details, baseline_alerts, baseline_ready=False)
        self.assertTrue(all(not alert.is_new for alert in alerts))

        follow_up_alerts = baseline_alerts + [WatchAlert(severity="warning", name="manual_test", detail="new condition")]
        updated, _, _ = apply_watch_state(
            details,
            follow_up_alerts,
            seen_session_ids=seen_sessions,
            seen_alert_keys=seen_alerts,
            baseline_ready=True,
        )
        self.assertTrue(any(alert.name == "manual_test" and alert.is_new for alert in updated))

    def test_watch_state_persists_by_scope(self) -> None:
        scope_key = build_watch_scope_key(
            days=7,
            project_name="project",
            cost_threshold_usd=10.0,
            token_threshold=1000,
            request_threshold=5,
            delta_pct_threshold=50.0,
        )
        save_watch_state(
            self.paths,
            scope_key,
            seen_session_ids={"session-1"},
            seen_alert_keys={("token_threshold", "Total tokens exceeded")},
        )
        loaded = load_watch_state(self.paths, scope_key)
        self.assertEqual(loaded.seen_session_ids, {"session-1"})
        self.assertEqual(loaded.seen_alert_keys, {("token_threshold", "Total tokens exceeded")})
        other_scope = load_watch_state(self.paths, "days=30|project=other")
        self.assertEqual(other_scope.seen_session_ids, set())
        self.assertEqual(other_scope.seen_alert_keys, set())

    def test_report_html_output(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        report = build_report(self.paths, "weekly", now=now)
        daily_points = summarize_daily(self.paths, days=7, now=now)
        html = format_report_html(report, daily_points=daily_points)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Codex Stats Weekly Report", html)
        self.assertIn("Top Sessions", html)
        self.assertIn("Top Projects", html)
        self.assertIn("Generated by codex-stats", html)
        self.assertIn("<svg", html)
        self.assertIn("Daily Token Trend", html)

    def test_dashboard_html_output(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        html = format_dashboard_html(dashboard)
        week_assets = format_dashboard_svg_assets(dashboard.windows[1])
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Codex usage at a glance.", html)
        self.assertIn("The selected tab updates the full page.", html)
        self.assertIn("Download PDF", html)
        self.assertIn("Summary JPG", html)
        self.assertIn('data-window="day"', html)
        self.assertIn('data-window="week"', html)
        self.assertIn('data-window="month"', html)
        self.assertIn('data-window="all"', html)
        self.assertIn("Projects, Sessions, and History", html)
        self.assertEqual(set(week_assets), {"summary-card", "cost-card", "focus-card", "projects-card", "heatmap-card"})
        self.assertIn("Codex Stats Week", week_assets["summary-card"])
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

    def test_report_svg_output(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        report = build_report(self.paths, "weekly", now=now)
        daily_points = summarize_daily(self.paths, days=7, now=now)
        svg = format_report_svg(report, daily_points=daily_points)
        assets = format_report_svg_assets(report, daily_points=daily_points)
        self.assertIn("<svg", svg)
        self.assertIn("Compact share card for release notes, README embeds, and social posts.", svg)
        self.assertIn("ANOMALIES", svg)
        self.assertIn("Generated by codex-stats", svg)
        self.assertEqual(set(assets), {"summary-card", "cost-card", "focus-card", "projects-card", "heatmap-card"})
        self.assertIn("Cost Snapshot", assets["cost-card"])
        self.assertIn("Focus Card", assets["focus-card"])
        self.assertIn("Project Snapshot", assets["projects-card"])
        self.assertIn("Heatmap", assets["heatmap-card"])

    def test_dashboard_html_includes_work_patterns_and_heatmap(self) -> None:
        now = datetime.fromisoformat("2026-04-03T18:30:00+05:30")
        dashboard = _build_dashboard(self.paths, now=now)
        html = format_dashboard_html(dashboard)
        self.assertIn("Work Patterns", html)
        self.assertIn("Activity Heatmap", html)
        self.assertIn("Top project concentration", html)


if __name__ == "__main__":
    unittest.main()
