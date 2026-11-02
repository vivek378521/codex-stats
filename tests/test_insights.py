from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.cli import _build_window
from codex_stats.display import (
    _format_capabilities_panel,
    _format_context_panel,
    _format_outcomes_panel,
    _format_waste_panel,
    _svg_waste_flow,
    format_dashboard_html,
)
from codex_stats.ingest import _read_rollout
from codex_stats.metrics import (
    summarize_behavior_from_details,
    summarize_context_hygiene_from_details,
    summarize_outcomes_from_details,
    summarize_waste_from_details,
)
from codex_stats.models import (
    CACHED_SEPARATE,
    TOOL_STATUS_COMPLETED,
    TOOL_STATUS_ERROR,
    CompactionEvent,
    DashboardData,
    SessionDetails,
    SessionRecord,
)
from codex_stats.tools import make_tool_call

NOW = datetime(2026, 4, 3, 12, 0, tzinfo=UTC)


def call(name: str, arguments=None, *, status: str = TOOL_STATUS_COMPLETED):
    return make_tool_call(name, arguments, status=status)


def detail(
    *,
    session_id: str = "s1",
    calls=(),
    cost: float | None = None,
    abandoned_turns: int = 0,
    compactions=(),
    peak_context_tokens: int | None = None,
    request_count: int = 1,
    input_tokens: int = 0,
) -> SessionDetails:
    session = SessionRecord(
        session_id=session_id,
        created_at=NOW,
        updated_at=NOW,
        cwd="/tmp/project",
        model="gpt-5.4",
        model_provider="openai",
        tokens_used=input_tokens,
        rollout_path=Path("/tmp/rollout.jsonl"),
        git_branch=None,
        git_origin_url=None,
        source="codex",
    )
    return SessionDetails(
        session=session,
        request_count=request_count,
        input_tokens=input_tokens,
        output_tokens=0,
        cached_input_tokens=0,
        reasoning_output_tokens=0,
        total_tokens_from_rollout=input_tokens,
        started_at=NOW,
        recorded_cost_usd=cost,
        token_accounting=CACHED_SEPARATE,
        tool_calls=tuple(calls),
        abandoned_turns=abandoned_turns,
        compaction_events=tuple(compactions),
        peak_context_tokens=peak_context_tokens,
    )


def window_for(details):
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


class ToolInsightExtractionTest(unittest.TestCase):
    def test_mcp_skill_and_subagent_identity(self) -> None:
        mcp = call("mcp__github__search", {"query": "bugs"})
        skill = call("Skill", {"skill": "deploy"})
        subagent = call("Task", {"subagent_type": "explore"})

        self.assertEqual(mcp.mcp_server, "github")
        self.assertEqual(skill.skill, "deploy")
        self.assertEqual(subagent.subagent_type, "explore")

    def test_shell_commands_expose_verb_verification_and_pr_creation(self) -> None:
        test = call("Bash", {"command": "uv run pytest -q"})
        pr = call("Bash", {"command": "gh pr create --fill"})
        quoted = call("Bash", {"command": 'rg "gh pr create" docs'})
        plain = call("Bash", {"command": "echo pytest"})

        self.assertEqual(test.verb, "pytest")
        self.assertTrue(test.is_verification)
        self.assertTrue(pr.is_pr_create)
        self.assertFalse(quoted.is_pr_create)
        self.assertFalse(plain.is_verification)

    def test_file_paths_are_extracted_from_arguments_and_commands(self) -> None:
        read = call("Read", {"file_path": "/tmp/a.py"})
        shell_read = call("Bash", {"command": "cat /tmp/b.py"})
        patch = call("apply_patch", "*** Begin Patch\n*** Update File: /tmp/c.py\n")

        self.assertEqual(read.file_path, "/tmp/a.py")
        self.assertEqual(shell_read.file_path, "/tmp/b.py")
        self.assertEqual(patch.file_path, "/tmp/c.py")
        self.assertTrue(shell_read.is_file_read)
        self.assertTrue(patch.is_file_edit)


class CodexCompactionExtractionTest(unittest.TestCase):
    def test_context_compaction_and_peak_context_are_captured(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "rollout.jsonl"
        events = [
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"input_tokens": 1000}},
                },
            },
            {"type": "event_msg", "payload": {"type": "context_compacted"}},
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"last_token_usage": {"input_tokens": 120}},
                },
            },
        ]
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

        details, _edits, _calls = _read_rollout(path)

        self.assertEqual(details["peak_context_tokens"], 1000)
        (compaction,) = details["compaction_events"]
        self.assertEqual(compaction.pre_tokens, 1000)
        self.assertEqual(compaction.post_tokens, 120)


class OutcomeTest(unittest.TestCase):
    def test_verification_after_last_edit_wins_over_completed(self) -> None:
        edited = call("Edit", {"file_path": "/tmp/a.py"})
        verified = call("Bash", {"command": "pytest -q"})
        summary = summarize_outcomes_from_details([detail(calls=(edited, verified))])

        self.assertEqual(summary.verified, 1)
        self.assertEqual(summary.verified_after_edit, 1)
        self.assertEqual(summary.verification_rate, 1.0)

    def test_priority_pr_interrupted_unresolved_completed(self) -> None:
        pr = call("Bash", {"command": "gh pr create --fill"})
        failure_a = call("Bash", {"command": "false a"}, status=TOOL_STATUS_ERROR)
        failure_b = call("Bash", {"command": "false b"}, status=TOOL_STATUS_ERROR)
        summary = summarize_outcomes_from_details(
            [
                detail(session_id="pr", calls=(pr,)),
                detail(
                    session_id="interrupted",
                    calls=(call("Edit", {"file_path": "/tmp/a.py"}),),
                    abandoned_turns=1,
                ),
                detail(session_id="errors", calls=(failure_a, failure_b)),
                detail(session_id="completed", calls=(call("Edit", {"file_path": "/tmp/a.py"}),)),
                detail(session_id="quiet"),
            ]
        )

        self.assertEqual(summary.pr_created, 1)
        self.assertEqual(summary.interrupted, 1)
        self.assertEqual(summary.unresolved_errors, 1)
        self.assertEqual(summary.completed, 1)
        self.assertEqual(summary.unclassified_sessions, 1)


class ContextHygieneTest(unittest.TestCase):
    def test_reread_is_counted_only_after_compaction(self) -> None:
        calls = (
            call("Read", {"file_path": "/tmp/a.py"}),
            call("Read", {"file_path": "/tmp/b.py"}),
            call("Read", {"file_path": "/tmp/a.py"}),
        )
        summary = summarize_context_hygiene_from_details(
            [
                detail(
                    calls=calls,
                    compactions=(CompactionEvent(after_call=2, pre_tokens=900, post_tokens=100),),
                    peak_context_tokens=900,
                )
            ]
        )

        self.assertEqual(summary.compactions, 1)
        self.assertEqual(summary.reads, 3)
        self.assertEqual(summary.rereads_after_compaction, 1)
        self.assertEqual(summary.average_pre_tokens, 900)
        self.assertEqual(summary.average_post_tokens, 100)

    def test_second_compaction_tracks_reads_from_after_the_first(self) -> None:
        calls = (
            call("Read", {"file_path": "/tmp/a.py"}),
            call("Read", {"file_path": "/tmp/b.py"}),
            call("Read", {"file_path": "/tmp/b.py"}),
        )
        summary = summarize_context_hygiene_from_details(
            [
                detail(
                    calls=calls,
                    compactions=(
                        CompactionEvent(after_call=1),
                        CompactionEvent(after_call=2),
                    ),
                )
            ]
        )

        self.assertEqual(summary.compactions, 2)
        self.assertEqual(summary.rereads_after_compaction, 1)

    def test_edit_clears_the_read_before_compaction(self) -> None:
        calls = (
            call("Read", {"file_path": "/tmp/a.py"}),
            call("Edit", {"file_path": "/tmp/a.py"}),
            call("Read", {"file_path": "/tmp/a.py"}),
        )
        summary = summarize_context_hygiene_from_details(
            [detail(calls=calls, compactions=(CompactionEvent(after_call=1),))]
        )

        self.assertEqual(summary.rereads_after_compaction, 0)


class CapabilityBreakdownTest(unittest.TestCase):
    def test_mcp_skills_and_subagents_are_counted_per_session(self) -> None:
        first = detail(
            session_id="a",
            calls=(
                call("mcp__github__search", {"query": "x"}),
                call("mcp__github__search", {"query": "y"}),
                call("Skill", {"skill": "deploy"}),
                call("Task", {"subagent_type": "explore"}),
            ),
        )
        second = detail(
            session_id="b",
            calls=(
                call("mcp__github__search", {"query": "z"}),
                call("Task", {}),
            ),
        )
        summary = summarize_behavior_from_details([first, second])

        self.assertEqual(
            [(entry.name, entry.calls, entry.sessions) for entry in summary.mcp_servers],
            [("github", 3, 2)],
        )
        self.assertEqual([(entry.name, entry.calls) for entry in summary.skills], [("deploy", 1)])
        self.assertEqual(
            [(entry.name, entry.calls) for entry in summary.subagent_types],
            [("explore", 1), ("general", 1)],
        )


class WasteLedgerTest(unittest.TestCase):
    def test_retry_reread_and_abandoned_buckets_are_priced(self) -> None:
        failed = call("Bash", {"command": "false"}, status=TOOL_STATUS_ERROR)
        fixed = call("Bash", {"command": "false"})
        read = call("Read", {"file_path": "/tmp/a.py"})
        first = detail(session_id="a", calls=(failed, fixed, read, read), cost=2.0)
        errors = (
            call("Bash", {"command": "false a"}, status=TOOL_STATUS_ERROR),
            call("Bash", {"command": "false b"}, status=TOOL_STATUS_ERROR),
        )
        second = detail(session_id="b", calls=errors, cost=1.0)
        summary = summarize_waste_from_details([first, second])
        buckets = {entry.bucket: entry for entry in summary.entries}

        self.assertEqual(buckets["retry"].amount, 1)
        self.assertEqual(buckets["retry"].cost_usd, 0.5)
        self.assertEqual(buckets["reread"].amount, 1)
        self.assertEqual(buckets["reread"].cost_usd, 0.5)
        self.assertEqual(buckets["abandoned"].amount, 1)
        self.assertEqual(buckets["abandoned"].cost_usd, 1.0)
        self.assertLessEqual(summary.waste_cost_usd, summary.total_cost_usd)

    def test_cache_miss_premium_uses_fresh_input_tokens(self) -> None:
        summary = summarize_waste_from_details(
            [detail(cost=1.0, request_count=2, input_tokens=1000)]
        )
        bucket = {entry.bucket: entry for entry in summary.entries}["cache_miss"]

        self.assertGreater(bucket.amount, 0)
        self.assertGreater(bucket.cost_usd, 0)


class InsightPanelsTest(unittest.TestCase):
    def test_renders_all_four_new_panels(self) -> None:
        details = [
            detail(
                calls=(
                    call("Edit", {"file_path": "/tmp/a.py"}),
                    call("Bash", {"command": "pytest -q"}),
                    call("mcp__github__search", {"query": "x"}),
                ),
                cost=2.0,
                compactions=(CompactionEvent(after_call=1, pre_tokens=900, post_tokens=100),),
                peak_context_tokens=900,
            )
        ]
        window = window_for(details)

        capabilities = _format_capabilities_panel(window)
        outcomes = _format_outcomes_panel(window)
        context = _format_context_panel(window)
        waste = _format_waste_panel(window)

        self.assertIn("MCP, Skills &amp; Subagents", capabilities)
        self.assertIn("github", capabilities)
        self.assertIn("Outcomes &amp; Verification", outcomes)
        self.assertIn("Verified after edit", outcomes)
        self.assertIn("Context Hygiene", context)
        self.assertIn("Re-reads After Compaction", context)
        self.assertIn("Waste Ledger", waste)
        self.assertIn("$2.00", waste)

        html = format_dashboard_html(DashboardData(generated_at=NOW, windows=[window]))
        self.assertIn("MCP, Skills &amp; Subagents", html)
        self.assertIn("Outcomes &amp; Verification", html)
        self.assertIn("Context Hygiene", html)
        self.assertIn("Waste Ledger", html)

    def test_waste_panel_draws_the_context_tax_flow(self) -> None:
        failed = call("Bash", {"command": "false"}, status=TOOL_STATUS_ERROR)
        fixed = call("Bash", {"command": "false"})
        read = call("Read", {"file_path": "/tmp/a.py"})
        window = window_for(
            [
                detail(
                    session_id="a",
                    calls=(failed, fixed, read, read),
                    cost=2.0,
                    request_count=2,
                    input_tokens=1000,
                    compactions=(CompactionEvent(after_call=2, pre_tokens=900, post_tokens=100),),
                    peak_context_tokens=900,
                )
            ]
        )

        flow = _svg_waste_flow(window)
        waste = _format_waste_panel(window)

        self.assertIn("<svg", flow)
        self.assertIn("TOTAL SPEND", flow)
        self.assertIn("Context tax", flow)
        self.assertIn("Re-read tax", flow)
        self.assertIn("Failure tax", flow)
        self.assertIn("Context Tax", waste)
        self.assertIn("Post-compaction re-reads", waste)

    def test_waste_flow_is_empty_when_nothing_was_wasted(self) -> None:
        window = window_for([detail(calls=(call("Read", {"file_path": "/tmp/a.py"}),), cost=1.0)])

        self.assertIn("No waste to visualize", _svg_waste_flow(window))


if __name__ == "__main__":
    unittest.main()
