"""Assertions for the HTML renderer.

``display.py`` is the largest module in the project and the one that decides what a
reader actually sees, so these tests pin the panels it emits and the values inside
them. They assert on rendered text rather than markup shape, because the markup is
expected to change and the numbers are not.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import _build_scope, _build_window
from codex_stats.display import (
    _fmt_idle,
    _format_branch_panel,
    _format_branch_note,
    _format_provider_panel,
    _format_reasoning_hint,
    format_dashboard_html,
    format_dashboard_svg_assets,
)
from codex_stats.metrics import summarize_takeaways
from codex_stats.models import (
    CACHED_SEPARATE,
    BehaviorSummary,
    DashboardData,
    SessionDetails,
    SessionRecord,
)

NOW = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)


def detail(
    *,
    session_id: str = "s1",
    branch: str | None = "main",
    project: str = "alpha",
    model: str = "gpt-5.4",
    model_provider: str = "openai",
    days_ago: int = 0,
    total_tokens: int = 10_000,
    reasoning_tokens: int = 0,
) -> SessionDetails:
    created = NOW - timedelta(days=days_ago)
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


def window_for(details: list[SessionDetails]) -> object:
    return _build_window(
        key="all",
        label="All Time",
        description="All recorded sessions.",
        current_details=details,
        previous_details=[],
        current_label="all time",
        previous_label="prior",
        trend_days=30,
        all_details=details,
        pricing=None,
        now=NOW,
    )


def empty_behavior() -> BehaviorSummary:
    return BehaviorSummary(
        total_calls=0,
        error_calls=0,
        repeated_calls=0,
        sessions_with_calls=0,
        abandoned_turns=0,
        read_calls=0,
        edit_calls=0,
        categories=[],
        tools=[],
        supported=False,
    )


class TagBalanceParser(HTMLParser):
    """Flags tags that are opened and never closed, or closed that were never opened.

    A dashboard that silently drops a closing tag still renders in a browser, so
    nothing else in the suite would notice.
    """

    VOID = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        if not self.stack:
            self.errors.append(f"stray </{tag}>")
            return
        if self.stack[-1] == tag:
            self.stack.pop()
            return
        if tag in self.stack:
            while self.stack and self.stack[-1] != tag:
                self.errors.append(f"unclosed <{self.stack[-1]}>")
                self.stack.pop()
            if self.stack:
                self.stack.pop()
        else:
            self.errors.append(f"stray </{tag}>")


class BranchPanelTest(unittest.TestCase):
    def test_renders_each_branch_with_its_numbers(self) -> None:
        window = window_for([detail(session_id="a", branch="feature", total_tokens=40_000)])
        html = _format_branch_panel(window)
        self.assertIn("<h2>Branches</h2>", html)
        self.assertIn("feature", html)
        self.assertIn("40,000", html)
        self.assertIn("alpha", html)

    def test_marks_quiet_branches_and_totals_their_spend(self) -> None:
        window = window_for(
            [
                detail(session_id="a", branch="shipped", days_ago=0),
                detail(session_id="b", branch="dropped", days_ago=45, total_tokens=80_000),
            ]
        )
        html = _format_branch_panel(window)
        self.assertIn("dropped", html)
        self.assertIn("is-idle", html)
        self.assertIn("Went quiet", html)
        self.assertIn("Idle spend", html)
        # A branch only earns the idle marker after the threshold, not just for being old.
        self.assertEqual(html.count("is-idle"), 1)

    def test_reports_no_idle_spend_when_nothing_went_quiet(self) -> None:
        window = window_for([detail(branch="fresh", days_ago=1)])
        html = _format_branch_panel(window)
        self.assertNotIn("is-idle", html)
        self.assertIn("<strong>None</strong><span>Idle spend</span>", html)

    def test_shows_repository_under_each_branch_name(self) -> None:
        window = window_for([detail(branch="main", project="beta")])
        self.assertIn('<span class="cell-sub">beta</span>', _format_branch_panel(window))

    def test_escapes_branch_and_project_names(self) -> None:
        window = window_for([detail(branch="<script>x</script>", project="a&b")])
        html = _format_branch_panel(window)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("a&amp;b", html)

    def test_empty_state_when_the_scope_records_no_branches(self) -> None:
        window = window_for([detail(branch=None)])
        html = _format_branch_panel(window)
        self.assertIn("No branch data for this view.", html)
        # The empty state has to name the limitation, or a quiet week looks like no work.
        self.assertIn("OpenCode never records one", html)

    def test_empty_state_when_there_is_no_summary_at_all(self) -> None:
        class NoBranches:
            branches = None

        self.assertIn("No branch data", _format_branch_panel(NoBranches()))

    def test_table_header_names_every_rendered_column(self) -> None:
        window = window_for([detail(branch="main")])
        html = _format_branch_panel(window)
        for column in ("Branch", "Sessions", "Tokens/session", "Tokens", "Cost", "Last active"):
            self.assertIn(f"<th>{column}</th>", html)

    def test_note_reports_untracked_sessions(self) -> None:
        window = window_for([detail(session_id="a", branch="main"), detail(session_id="b", branch=None)])
        note = _format_branch_note(window.branches)
        self.assertIn("1 of 2 sessions", note)
        self.assertIn("1 not recorded on a branch", note)

    def test_note_names_the_worst_quiet_branch(self) -> None:
        window = window_for([detail(session_id="a", branch="cold", days_ago=30)])
        note = _format_branch_note(window.branches)
        self.assertIn("alpha / cold", note)
        self.assertIn("30 days", note)


class ProviderPanelTest(unittest.TestCase):
    def test_lists_vendors_with_cost_share(self) -> None:
        window = window_for(
            [
                detail(session_id="a", model="gpt-5.4", model_provider="openai", total_tokens=80_000),
                detail(session_id="b", model="claude-opus-5", model_provider="anthropic", total_tokens=20_000),
            ]
        )
        html = _format_provider_panel(window)
        self.assertIn("<h2>Providers</h2>", html)
        self.assertIn("OpenAI", html)
        self.assertIn("Anthropic", html)
        self.assertIn("Cost Share by Vendor", html)

    def test_explains_unattributed_spend_instead_of_hiding_it(self) -> None:
        window = window_for(
            [
                detail(session_id="a", model="gpt-5.4", model_provider="openai"),
                detail(session_id="b", model="big-pickle", model_provider="opencode"),
            ]
        )
        html = _format_provider_panel(window)
        self.assertIn("Unidentified", html)
        self.assertIn("internal codename", html)

    def test_no_codename_note_when_everything_resolved(self) -> None:
        window = window_for([detail(model="gpt-5.4", model_provider="openai")])
        self.assertNotIn("internal codename", _format_provider_panel(window))

    def test_table_header_names_every_rendered_column(self) -> None:
        html = _format_provider_panel(window_for([detail()]))
        for column in ("Vendor", "Sessions", "Tokens", "Cost", "Share"):
            self.assertIn(f"<th>{column}</th>", html)

    def test_escapes_vendor_names(self) -> None:
        window = window_for([detail(model="&<>", model_provider="x")])
        self.assertNotIn("<>", _format_provider_panel(window))

    def test_empty_state_without_sessions(self) -> None:
        html = _format_provider_panel(window_for([]))
        self.assertIn("No provider data for this view.", html)


class ReasoningHintTest(unittest.TestCase):
    def test_hint_reports_the_token_count_when_present(self) -> None:
        window = window_for([detail(total_tokens=1_000, reasoning_tokens=250)])
        self.assertIn("250 tokens, billed as output", _format_reasoning_hint(window.summary))

    def test_hint_says_not_reported_when_absent(self) -> None:
        window = window_for([detail(reasoning_tokens=0)])
        hint = _format_reasoning_hint(window.summary)
        self.assertIn("Not reported by these tools", hint)
        self.assertNotIn("billed as output", hint)

    def test_tile_shows_a_share_when_reasoning_exists(self) -> None:
        html = format_dashboard_html(
            DashboardData(generated_at=NOW, windows=[window_for([detail(total_tokens=1_000, reasoning_tokens=250)])])
        )
        self.assertIn("Reasoning share", html)
        self.assertIn("250 tokens, billed as output", html)

    def test_tile_shows_not_applicable_without_reasoning(self) -> None:
        html = format_dashboard_html(
            DashboardData(generated_at=NOW, windows=[window_for([detail(reasoning_tokens=0)])])
        )
        self.assertIn("Not reported by these tools", html)


class IdleLabelTest(unittest.TestCase):
    def test_recent_and_future_read_as_today(self) -> None:
        self.assertEqual(_fmt_idle(0), "today")
        self.assertEqual(_fmt_idle(-3), "today")

    def test_singular_and_plural_days(self) -> None:
        self.assertEqual(_fmt_idle(1), "1 day ago")
        self.assertEqual(_fmt_idle(2), "2 days ago")

    def test_switches_to_months_past_a_month(self) -> None:
        self.assertEqual(_fmt_idle(29), "29 days ago")
        self.assertEqual(_fmt_idle(30), "1 mo ago")
        self.assertEqual(_fmt_idle(75), "2 mo ago")


class DashboardStructureTest(unittest.TestCase):
    def _render(self, details: list[SessionDetails], **dashboard_kwargs) -> str:
        return format_dashboard_html(
            DashboardData(generated_at=NOW, windows=[window_for(details)], **dashboard_kwargs)
        )

    def test_output_is_balanced_markup(self) -> None:
        parser = TagBalanceParser()
        parser.feed(self._render([detail(), detail(session_id="b", project="beta")]))
        self.assertEqual(parser.errors, [])
        self.assertEqual(parser.stack, [])

    def test_output_is_balanced_when_empty(self) -> None:
        parser = TagBalanceParser()
        parser.feed(self._render([]))
        self.assertEqual(parser.errors, [])
        self.assertEqual(parser.stack, [])

    def test_every_tab_and_window_is_present(self) -> None:
        scope = _build_scope(
            key="codex",
            label="Codex",
            description="Codex only.",
            source="codex",
            details=[detail()],
            pricing=None,
            now=NOW,
        )
        html = format_dashboard_html(DashboardData(generated_at=NOW, scopes=[scope]))
        # The scope tab row, then the window row, which is labelled for humans
        # rather than by key.
        self.assertIn(">Codex<", html)
        for label in ("Today", "Last 7 Days", "Last 30 Days", "All Time"):
            self.assertIn(f">{label}<", html)

    def test_all_four_windows_render_their_own_panels(self) -> None:
        scope = _build_scope(
            key="codex",
            label="Codex",
            description="Codex only.",
            source="codex",
            details=[detail()],
            pricing=None,
            now=NOW,
        )
        html = format_dashboard_html(DashboardData(generated_at=NOW, scopes=[scope]))
        for window in scope.windows:
            with self.subTest(window=window.key):
                self.assertIn(f'data-window="{window.key}"', html)
        # One populated branch panel per window, since all four read the same details.
        self.assertEqual(html.count("<h2>Branches</h2>"), 4)
        self.assertEqual(html.count("<h2>Providers</h2>"), 4)

    def test_coverage_note_is_rendered_once_for_the_page(self) -> None:
        # A bounded history qualifies every number on the page, so it belongs above
        # the tabs once rather than repeated inside all twenty windows.
        html = self._render([detail()], coverage_note="Showing 10 of 99 sessions.")
        self.assertEqual(html.count("Showing 10 of 99 sessions."), 1)

    def test_coverage_note_absent_by_default(self) -> None:
        self.assertNotIn("Partial history.", self._render([detail()]))

    def test_generation_time_is_shown(self) -> None:
        self.assertIn("2026-04-03 12:00 UTC", self._render([detail()]))

    def test_branch_and_provider_panels_are_present_on_a_populated_window(self) -> None:
        html = self._render([detail(branch="main")])
        self.assertIn("<h2>Branches</h2>", html)
        self.assertIn("<h2>Providers</h2>", html)


class SvgAssetTest(unittest.TestCase):
    def test_assets_are_well_formed_svg_documents(self) -> None:
        window = window_for([detail()])
        assets = format_dashboard_svg_assets(window, scope_label="Codex")
        self.assertTrue(assets)
        for name, svg in assets.items():
            with self.subTest(asset=name):
                self.assertTrue(svg.startswith("<svg"), svg[:40])
                self.assertIn("</svg>", svg)

    def test_assets_survive_json_round_trip(self) -> None:
        # The page embeds these through JSON.stringify, so a stray quote would
        # break the export path rather than the initial render.
        window = window_for([detail(branch="quote\"branch")])
        assets = format_dashboard_svg_assets(window, scope_label="Codex")
        restored = json.loads(json.dumps(assets))
        self.assertEqual(set(restored), set(assets))


class TakeawayWiringTest(unittest.TestCase):
    def test_quiet_branch_facts_survive_a_full_takeaway_list(self) -> None:
        window = window_for(
            [
                detail(session_id="a", branch="shipped", days_ago=0),
                detail(session_id="b", branch="forgotten", days_ago=60, total_tokens=90_000),
            ]
        )
        lines = summarize_takeaways(
            summary=window.summary,
            comparison=window.comparison,
            costs=window.costs,
            insights=window.insights,
            file_impact=window.file_impact,
            behavior=empty_behavior(),
            branches=window.branches,
        )
        self.assertTrue(any("forgotten" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()