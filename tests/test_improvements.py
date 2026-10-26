from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import _budget_note, _build_dashboard, _open_report_in_browser
from codex_stats.config import BudgetConfig, Paths, PricingConfig
from codex_stats.dsh_ingest import dsh_decoder_note
from codex_stats.metrics import (
    filter_details_by_project,
    summarize_efficiency_trend,
    summarize_projects_from_details,
    summarize_runway,
)
from codex_stats.models import (
    TOOL_CATEGORY_EDIT,
    TOOL_CATEGORY_READ,
    CostSummary,
    DailyPoint,
    FileEdit,
    SessionDetails,
    SessionRecord,
    SourceHealth,
    ToolCall,
)
from codex_stats.sources import Source, _connect_sqlite
from codex_stats.state import IngestCache, ingest_fingerprint

NOW = datetime(2026, 4, 15, 12, tzinfo=UTC)


def detail(
    *,
    session_id: str,
    cwd: str,
    created: datetime,
    tokens: int = 1000,
    source: str = "codex",
    read_calls: int = 1,
    edit_calls: int = 1,
    edits: int = 10,
) -> SessionDetails:
    calls = tuple(
        [ToolCall(name="Read", category=TOOL_CATEGORY_READ, fingerprint=f"r{i}") for i in range(read_calls)]
        + [ToolCall(name="Edit", category=TOOL_CATEGORY_EDIT, fingerprint=f"e{i}") for i in range(edit_calls)]
    )
    file_edits = (FileEdit(path=f"{cwd}/file.py", action="updated", insertions=edits, deletions=0),) if edits else ()
    return SessionDetails(
        session=SessionRecord(
            session_id=session_id,
            created_at=created,
            updated_at=created,
            cwd=cwd,
            model="gpt-5",
            model_provider="openai",
            tokens_used=tokens,
            rollout_path=Path("/tmp/rollout.jsonl"),
            git_branch="main",
            git_origin_url=None,
            source=source,
        ),
        request_count=2,
        input_tokens=tokens // 2,
        output_tokens=tokens // 2,
        cached_input_tokens=0,
        reasoning_output_tokens=0,
        total_tokens_from_rollout=tokens,
        started_at=created,
        tool_calls=calls,
        file_edits=file_edits,
    )


class ProjectGroupingTests(unittest.TestCase):
    def test_same_basename_in_different_parents_stays_separate(self) -> None:
        details = [
            detail(session_id="a", cwd="/repos/one/app", created=NOW),
            detail(session_id="b", cwd="/repos/two/app", created=NOW),
        ]
        projects = summarize_projects_from_details(details)
        self.assertEqual([entry.name for entry in projects], ["one/app", "two/app"])

        filtered = filter_details_by_project(details, "one/app")
        self.assertEqual([item.session.session_id for item in filtered], ["a"])


class EfficiencyTrendTests(unittest.TestCase):
    def test_buckets_by_week_instead_of_returning_empty_points(self) -> None:
        details = [
            detail(session_id="a", cwd="/repos/a", created=datetime(2026, 1, 6, tzinfo=UTC)),
            detail(session_id="b", cwd="/repos/a", created=datetime(2026, 1, 20, tzinfo=UTC)),
            detail(session_id="c", cwd="/repos/a", created=datetime(2026, 2, 3, tzinfo=UTC)),
        ]
        trend = summarize_efficiency_trend(details, ["ignored"], now=datetime(2026, 2, 10, tzinfo=UTC))
        self.assertTrue(trend.supported)
        self.assertEqual(len(trend.points), 3)
        self.assertEqual(trend.points[0].label, "2026-01-05")
        self.assertIsNotNone(trend.points[0].cost_per_1k_lines)
        self.assertIsNotNone(trend.points[0].read_write_ratio)


class RunwayTests(unittest.TestCase):
    def test_uses_calendar_month_spend_not_the_rolling_month(self) -> None:
        costs = CostSummary(
            today_cost_usd=1,
            week_cost_usd=7,
            month_cost_usd=50,
            projected_monthly_cost_usd=50,
            highest_session_cost_usd=1,
            calendar_month_cost_usd=20,
        )
        points = [
            DailyPoint(day=(NOW.date() - timedelta(days=offset)).isoformat(), total_tokens=1, requests=1, estimated_cost_usd=1)
            for offset in range(7)
        ]
        runway = summarize_runway(
            points,
            costs=costs,
            budget=BudgetConfig(monthly_limit_usd=100, warn_at_ratio=0.8),
            now=NOW,
        )
        self.assertEqual(runway.spend_last_days_usd, 7)
        self.assertEqual(runway.days_until_exceed, 80)
        self.assertEqual(runway.status, "on_track")


class BudgetNoteTests(unittest.TestCase):
    def test_project_limit_is_reported(self) -> None:
        details = [detail(session_id="a", cwd="/repos/app", created=NOW)]
        note = _budget_note(
            BudgetConfig(monthly_limit_usd=None, project_limits={"app": 0.000001}, warn_at_ratio=0.5),
            PricingConfig(),
            details,
            NOW,
        )
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("project budget for app", note)

    def test_project_limit_works_without_a_monthly_limit(self) -> None:
        details = [detail(session_id="a", cwd="/repos/app", created=NOW)]
        note = _budget_note(
            BudgetConfig(project_limits={"app": 0.000001}, warn_at_ratio=0.5),
            PricingConfig(),
            details,
            NOW,
        )
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("project budget for app", note)


class SourceIsolationTests(unittest.TestCase):
    def test_one_failing_source_does_not_hide_the_others(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = Paths(
                codex_home=root / ".codex",
                state_db=root / ".codex" / "state_5.sqlite",
                sessions_dir=root / ".codex" / "sessions",
                config_dir=root / "config",
                config_file=root / "config" / "config.toml",
                output_dir=root / "cache",
                dashboard_file=root / "cache" / "dashboard.html",
            )

            def broken() -> list[SessionDetails]:
                raise RuntimeError("bad transcript")

            good_detail = detail(session_id="good", cwd="/repos/app", created=NOW)
            sources = [
                Source("bad", "Bad", "", True, str(root), broken, lambda: (0, 0)),
                Source("good", "Good", "", True, str(root), lambda: [good_detail], lambda: (1, 1)),
            ]
            with mock.patch("codex_stats.cli.iter_sources", return_value=sources):
                dashboard = _build_dashboard(paths, now=NOW)
            health = {item.key: item for item in dashboard.source_health}
            self.assertIn("bad transcript", health["bad"].error or "")
            self.assertEqual(health["good"].sessions, 1)
            overview = next(scope for scope in dashboard.scopes if scope.key == "overview")
            self.assertEqual(overview.windows[0].summary.sessions, 1)


class SourceHealthRenderingTests(unittest.TestCase):
    def test_health_data_is_serializable(self) -> None:
        item = SourceHealth("codex", "Codex", True, "/tmp/codex", 2)
        self.assertEqual(item.to_dict()["sessions"], 2)


class IngestCacheTests(unittest.TestCase):
    def test_round_trips_and_invalidates_on_fingerprint_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            source_dir.mkdir()
            file_path = source_dir / "one.json"
            file_path.write_text("one", encoding="utf-8")
            cache = IngestCache(root / "cache")
            fingerprint = ingest_fingerprint(str(source_dir), "")
            cache.put("codex", fingerprint, ["cached"])
            cache.save()

            reloaded = IngestCache(root / "cache")
            self.assertEqual(reloaded.get("codex", fingerprint), ["cached"])
            self.assertIsNone(reloaded.get("codex", "different"))


class ReadOnlySqliteTests(unittest.TestCase):
    def test_existing_database_is_opened_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE sample (id INTEGER)")
            connection.commit()
            connection.close()

            read_only = _connect_sqlite(path)
            self.addCleanup(read_only.close)
            with self.assertRaises(sqlite3.OperationalError):
                read_only.execute("CREATE TABLE other (id INTEGER)")


class ZstdNoteTests(unittest.TestCase):
    def test_note_explains_missing_decoder_for_compressed_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            project = sessions / "project"
            session = project / "session"
            session.mkdir(parents=True)
            (session / "session.v4.jsonl.zstd").write_bytes(b"compressed")
            with mock.patch("codex_stats.dsh_ingest.dsh_zstd_available", return_value=False):
                note = dsh_decoder_note(sessions)
        self.assertIsNotNone(note)
        assert note is not None
        self.assertIn("pip install zstandard", note)


class BrowserFallbackTests(unittest.TestCase):
    def test_returns_false_when_no_browser_is_available(self) -> None:
        with mock.patch("codex_stats.cli.webbrowser.open", return_value=False):
            self.assertFalse(_open_report_in_browser(Path("/tmp/dashboard.html")))


if __name__ == "__main__":
    unittest.main()
