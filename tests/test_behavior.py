from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.display import _format_behavior_panel
from codex_stats.ingest import _read_rollout
from codex_stats.metrics import (
    summarize_behavior_from_details,
    summarize_behavior_takeaways,
    summarize_takeaways,
)
from codex_stats.models import (
    CACHED_SEPARATE,
    TOOL_CATEGORY_EDIT,
    TOOL_CATEGORY_EXEC,
    TOOL_CATEGORY_OTHER,
    TOOL_CATEGORY_READ,
    TOOL_STATUS_COMPLETED,
    TOOL_STATUS_ERROR,
    TOOL_STATUS_UNKNOWN,
    SessionDetails,
    SessionRecord,
    ToolCall,
)
from codex_stats.sources import _connect_sqlite, _hermes_tool_calls, _opencode_tool_calls, _parse_claude_session
from codex_stats.tools import (
    coalesce_output_text,
    make_tool_call,
    normalize_tool_name,
    output_looks_failed,
    tool_category,
    tool_fingerprint,
)

NOW = datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc)


def make_detail(
    *,
    session_id: str = "s1",
    tool_calls: tuple[ToolCall, ...] = (),
    abandoned_turns: int = 0,
    source: str = "codex",
    days_ago: int = 0,
) -> SessionDetails:
    created = NOW - timedelta(days=days_ago)
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
        cached_input_tokens=10,
        reasoning_output_tokens=0,
        total_tokens_from_rollout=160,
        started_at=created,
        token_accounting=CACHED_SEPARATE,
        tool_calls=tool_calls,
        abandoned_turns=abandoned_turns,
    )


def call(name: str, args: str = "x", *, status: str = TOOL_STATUS_COMPLETED, duration_ms=None) -> ToolCall:
    return make_tool_call(name, args, status=status, duration_ms=duration_ms)


class ToolTaxonomyTest(unittest.TestCase):
    """The taxonomy has to agree across every CLI, so it is pinned to real tool names."""

    def test_observed_names_map_to_expected_categories(self) -> None:
        expected = {
            # Codex rollout names
            "exec_command": TOOL_CATEGORY_EXEC,
            "apply_patch": TOOL_CATEGORY_EDIT,
            "exec": TOOL_CATEGORY_EXEC,
            "write_stdin": TOOL_CATEGORY_EXEC,
            "wait": TOOL_CATEGORY_EXEC,
            "update_plan": "plan",
            # Claude Code transcript names
            "Bash": TOOL_CATEGORY_EXEC,
            "Read": TOOL_CATEGORY_READ,
            "Edit": TOOL_CATEGORY_EDIT,
            "Write": TOOL_CATEGORY_EDIT,
            "TaskUpdate": "plan",
            "TaskCreate": "plan",
            "AskUserQuestion": TOOL_CATEGORY_OTHER,
            "Agent": "agent",
            "ExitPlanMode": "plan",
            "EnterPlanMode": "plan",
            "TaskList": "plan",
            # OpenCode part names
            "bash": TOOL_CATEGORY_EXEC,
            "edit": TOOL_CATEGORY_EDIT,
            "read": TOOL_CATEGORY_READ,
            "write": TOOL_CATEGORY_EDIT,
            "todowrite": "plan",
            "grep": "search",
            "question": TOOL_CATEGORY_OTHER,
            "glob": "search",
            "websearch": "web",
            "webfetch": "web",
            "task": "agent",
            "invalid": TOOL_CATEGORY_OTHER,
        }
        for name, category in expected.items():
            with self.subTest(name=name):
                self.assertEqual(tool_category(name), category)

    def test_case_and_separator_variants_collapse(self) -> None:
        for variant in ("MultiEdit", "multi_edit", "multi-edit", "multiedit"):
            with self.subTest(variant=variant):
                self.assertEqual(tool_category(variant), TOOL_CATEGORY_EDIT)

    def test_mcp_prefix_is_stripped(self) -> None:
        self.assertEqual(normalize_tool_name("mcp__my_server__Read"), "read")
        self.assertEqual(tool_category("mcp__my_server__Read"), TOOL_CATEGORY_READ)

    def test_thread_is_not_misread_as_read(self) -> None:
        # "thread" contains "read" and would otherwise land in the read bucket.
        self.assertEqual(tool_category("read_thread_messages"), TOOL_CATEGORY_OTHER)

    def test_write_stdin_is_exec_not_edit(self) -> None:
        self.assertEqual(tool_category("write_stdin"), TOOL_CATEGORY_EXEC)

    def test_unknown_names_fall_back_to_other(self) -> None:
        self.assertEqual(tool_category("zzzz"), TOOL_CATEGORY_OTHER)
        self.assertEqual(tool_category(None), TOOL_CATEGORY_OTHER)
        self.assertEqual(tool_category(""), TOOL_CATEGORY_OTHER)


class FingerprintTest(unittest.TestCase):
    def test_same_work_produces_same_fingerprint(self) -> None:
        a = tool_fingerprint("Bash", json.dumps({"command": "pytest -q"}))
        b = tool_fingerprint("Bash", json.dumps({"command": "pytest -q"}))
        self.assertEqual(a, b)

    def test_different_work_differs(self) -> None:
        a = tool_fingerprint("Bash", json.dumps({"command": "pytest -q"}))
        b = tool_fingerprint("Bash", json.dumps({"command": "pytest"}))
        self.assertNotEqual(a, b)

    def test_bookkeeping_fields_do_not_defeat_matching(self) -> None:
        """A differing description must not hide a repeated command."""
        a = tool_fingerprint("Bash", json.dumps({"command": "ls", "description": "one"}))
        b = tool_fingerprint("Bash", json.dumps({"command": "ls", "description": "two"}))
        self.assertEqual(a, b)

    def test_whitespace_is_normalized(self) -> None:
        a = tool_fingerprint("Bash", "ls   -la")
        b = tool_fingerprint("Bash", "ls -la")
        self.assertEqual(a, b)

    def test_tool_name_is_part_of_identity(self) -> None:
        self.assertNotEqual(tool_fingerprint("Read", "x"), tool_fingerprint("Edit", "x"))


class FailureDetectionTest(unittest.TestCase):
    """Codex has no per-call status, so detection must err low rather than high."""

    def test_structured_failure_headers(self) -> None:
        self.assertTrue(output_looks_failed("Script failed\nWall time 0.1 seconds"))
        self.assertTrue(output_looks_failed("apply_patch verification failed: no match"))

    def test_nonzero_exit_code(self) -> None:
        self.assertTrue(output_looks_failed("Command: ls\nExit code: 2"))
        self.assertFalse(output_looks_failed("Command: ls\nExit code: 0"))

    def test_source_code_containing_error_words_is_not_a_failure(self) -> None:
        """Regression: scanning the body flagged files the agent merely read."""
        output = "import x\nconst error = 'invalid'\nfunction readLog() {}\n"
        self.assertFalse(output_looks_failed(output))

    def test_successful_output_is_not_a_failure(self) -> None:
        self.assertFalse(output_looks_failed("Script completed\nWall time 0.1 seconds\n\nall good"))
        self.assertFalse(output_looks_failed(""))
        self.assertFalse(output_looks_failed(None))

    def test_coalesce_output_text_handles_block_lists(self) -> None:
        blocks = [{"type": "input_text", "text": "Script failed"}, {"type": "input_text", "text": "more"}]
        self.assertIn("Script failed", coalesce_output_text(blocks))
        self.assertIn("Script failed", coalesce_output_text("Script failed"))


class CodexExtractionTest(unittest.TestCase):
    def _write(self, events: list[dict]) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "rollout.jsonl"
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
        return path

    def test_extracts_calls_names_and_statuses(self) -> None:
        path = self._write(
            [
                {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "arguments": '{"cmd":"ls"}', "call_id": "c1"}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": [{"type": "input_text", "text": "Script completed\nok"}]}},
                {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "input": "*** Begin Patch", "call_id": "c2", "status": "completed"}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c2", "output": "apply_patch verification failed: nope"}},
            ]
        )
        details, _edits, calls = _read_rollout(path)
        self.assertEqual(len(calls), 2)
        self.assertEqual([c.name for c in calls], ["exec_command", "apply_patch"])
        self.assertEqual(calls[0].status, TOOL_STATUS_COMPLETED)
        self.assertEqual(calls[1].status, TOOL_STATUS_ERROR)

    def test_counts_abandoned_turns(self) -> None:
        path = self._write(
            [
                {"type": "event_msg", "payload": {"type": "turn_aborted", "reason": "interrupted"}},
                {"type": "event_msg", "payload": {"type": "turn_aborted", "reason": "interrupted"}},
            ]
        )
        details, _edits, _calls = _read_rollout(path)
        self.assertEqual(details["abandoned_turns"], 2)

    def test_missing_rollout_yields_no_calls(self) -> None:
        details, edits, calls = _read_rollout(Path("/nonexistent/rollout.jsonl"))
        self.assertEqual(calls, [])
        self.assertEqual(edits, [])

    def test_output_before_call_is_still_matched(self) -> None:
        path = self._write(
            [
                {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1", "output": "Script failed"}},
                {"type": "response_item", "payload": {"type": "function_call", "name": "Bash", "arguments": "{}", "call_id": "c1"}},
            ]
        )
        _details, _edits, calls = _read_rollout(path)
        self.assertEqual(calls[0].status, TOOL_STATUS_ERROR)


class ClaudeExtractionTest(unittest.TestCase):
    def _transcript(self, events: list[dict]) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        project = Path(tmpdir.name) / "proj"
        project.mkdir()
        path = project / "session.jsonl"
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
        return path

    def test_tool_use_and_tool_result_pairing(self) -> None:
        path = self._transcript(
            [
                {
                    "type": "assistant",
                    "timestamp": "2026-04-03T10:00:00Z",
                    "cwd": "/tmp/p",
                    "message": {
                        "model": "claude-opus-4.6",
                        "content": [
                            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}},
                            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/a.py"}},
                        ],
                    },
                },
                {
                    "type": "user",
                    "timestamp": "2026-04-03T10:00:02Z",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": "t1", "is_error": False},
                            {"type": "tool_result", "tool_use_id": "t2", "is_error": True},
                        ]
                    },
                },
            ]
        )
        details = _parse_claude_session(path)
        assert details is not None
        self.assertEqual([c.name for c in details.tool_calls], ["Bash", "Read"])
        self.assertEqual(details.tool_calls[0].status, TOOL_STATUS_COMPLETED)
        self.assertEqual(details.tool_calls[1].status, TOOL_STATUS_ERROR)

    def test_duration_uses_result_timestamp(self) -> None:
        path = self._transcript(
            [
                {"type": "assistant", "timestamp": "2026-04-03T10:00:00Z", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}},
                {"type": "user", "timestamp": "2026-04-03T10:00:05Z", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]}},
            ]
        )
        details = _parse_claude_session(path)
        assert details is not None
        self.assertEqual(details.tool_calls[0].duration_ms, 5000)

    def test_call_without_result_is_unknown_and_untimed(self) -> None:
        path = self._transcript(
            [
                {"type": "assistant", "timestamp": "2026-04-03T10:00:00Z", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}},
                {"type": "user", "timestamp": "2026-04-03T10:09:00Z", "message": {"content": []}},
            ]
        )
        details = _parse_claude_session(path)
        assert details is not None
        self.assertEqual(details.tool_calls[0].status, TOOL_STATUS_UNKNOWN)
        self.assertIsNone(details.tool_calls[0].duration_ms)

    def test_control_tools_are_not_failures(self) -> None:
        path = self._transcript(
            [
                {
                    "type": "assistant",
                    "timestamp": "2026-04-03T10:00:00Z",
                    "message": {
                        "content": [
                            {"type": "tool_use", "id": "t1", "name": "AskUserQuestion", "input": {}},
                            {"type": "tool_use", "id": "t2", "name": "ExitPlanMode", "input": {}},
                            {"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "ls"}},
                        ]
                    },
                },
                {
                    "type": "user",
                    "timestamp": "2026-04-03T10:00:02Z",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": "t1", "is_error": True},
                            {"type": "tool_result", "tool_use_id": "t2", "is_error": True},
                            {"type": "tool_result", "tool_use_id": "t3", "is_error": True},
                        ]
                    },
                },
            ]
        )
        details = _parse_claude_session(path)
        assert details is not None
        self.assertEqual(details.tool_calls[0].status, TOOL_STATUS_UNKNOWN)
        self.assertEqual(details.tool_calls[1].status, TOOL_STATUS_UNKNOWN)
        self.assertEqual(details.tool_calls[2].status, TOOL_STATUS_ERROR)
        summary = summarize_behavior_from_details([details])
        self.assertEqual(summary.error_calls, 1)


class OpenCodeExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.connection = _connect_sqlite(Path(tmpdir.name) / "opencode.db")
        self.connection.execute("CREATE TABLE part (id text, message_id text, session_id text, data text)")

    def _add(self, session_id: str, part: dict) -> None:
        self.connection.execute(
            "INSERT INTO part VALUES (?,?,?,?)",
            (part.get("id", "x"), "m", session_id, json.dumps(part)),
        )

    def test_reads_status_and_duration(self) -> None:
        self._add("s1", {"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": "ls"}, "time": {"start": 1000, "end": 1500}}})
        self._add("s1", {"type": "tool", "tool": "edit", "state": {"status": "error", "input": {"filePath": "/a"}}})
        self._add("s1", {"type": "text", "text": "ignored"})
        self.connection.commit()
        calls = _opencode_tool_calls(self.connection, {"s1"})["s1"]
        self.assertEqual([c.name for c in calls], ["bash", "edit"])
        self.assertEqual(calls[0].status, TOOL_STATUS_COMPLETED)
        self.assertEqual(calls[0].duration_ms, 500)
        self.assertEqual(calls[1].status, TOOL_STATUS_ERROR)
        self.assertIsNone(calls[1].duration_ms)

    def test_filters_to_requested_sessions(self) -> None:
        self._add("s1", {"type": "tool", "tool": "read", "state": {"status": "completed"}})
        self._add("s2", {"type": "tool", "tool": "read", "state": {"status": "completed"}})
        self.connection.commit()
        self.assertEqual(list(_opencode_tool_calls(self.connection, {"s1"})), ["s1"])

    def test_malformed_part_is_skipped(self) -> None:
        self.connection.execute("INSERT INTO part VALUES ('x','m','s1','not json')")
        self.connection.commit()
        self.assertEqual(_opencode_tool_calls(self.connection, {"s1"}), {})

    def test_no_sessions_short_circuits(self) -> None:
        self.assertEqual(_opencode_tool_calls(self.connection, set()), {})


class HermesExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.connection = _connect_sqlite(Path(tmpdir.name) / "state.db")
        self.connection.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, tool_calls TEXT, tool_call_id TEXT, effect_disposition TEXT)"
        )

    def _add_calls(self, session_id: str, entries: list[dict]) -> None:
        self.connection.execute(
            "INSERT INTO messages (session_id, tool_calls) VALUES (?,?)",
            (session_id, json.dumps(entries)),
        )

    def test_result_status_and_denial(self) -> None:
        self._add_calls(
            "s1",
            [
                {"id": "c1", "function": {"name": "Read", "arguments": json.dumps({"file_path": "/a"})}},
                {"id": "c2", "function": {"name": "Bash", "arguments": json.dumps({"command": "rm -rf /"})}},
            ],
        )
        self.connection.execute("INSERT INTO messages (session_id, tool_call_id) VALUES ('s1','c1')")
        self.connection.execute("INSERT INTO messages (session_id, tool_call_id, effect_disposition) VALUES ('s1','c2','denied')")
        self.connection.commit()
        calls = _hermes_tool_calls(self.connection, {"s1"})["s1"]
        self.assertEqual(calls[0].status, TOOL_STATUS_COMPLETED)
        self.assertEqual(calls[1].status, TOOL_STATUS_ERROR)

    def test_call_without_result_is_unknown(self) -> None:
        self._add_calls("s1", [{"id": "c9", "function": {"name": "Write", "arguments": "{}"}}])
        self.connection.commit()
        calls = _hermes_tool_calls(self.connection, {"s1"})["s1"]
        self.assertEqual(calls[0].status, TOOL_STATUS_UNKNOWN)

    def test_sessions_do_not_leak_into_each_other(self) -> None:
        self._add_calls("s1", [{"id": "c1", "function": {"name": "Read", "arguments": "{}"}}])
        self._add_calls("s2", [{"id": "c2", "function": {"name": "Bash", "arguments": "{}"}}])
        self.connection.execute("INSERT INTO messages (session_id, tool_call_id) VALUES ('s1','c1')")
        self.connection.commit()
        calls = _hermes_tool_calls(self.connection, {"s1", "s2"})
        self.assertEqual(calls["s1"][0].status, TOOL_STATUS_COMPLETED)
        self.assertEqual(calls["s2"][0].status, TOOL_STATUS_UNKNOWN)


class BehaviorSummaryTest(unittest.TestCase):
    def test_unsupported_when_nothing_recorded(self) -> None:
        summary = summarize_behavior_from_details([make_detail()])
        self.assertFalse(summary.supported)
        self.assertEqual(summary.total_calls, 0)
        self.assertIsNone(summary.error_rate)

    def test_aggregates_categories_and_tools(self) -> None:
        details = [
            make_detail(session_id="s1", tool_calls=(call("Bash"), call("Read"), call("Read"))),
            make_detail(session_id="s2", tool_calls=(call("Edit", status=TOOL_STATUS_ERROR),)),
        ]
        summary = summarize_behavior_from_details(details)
        self.assertTrue(summary.supported)
        self.assertEqual(summary.total_calls, 4)
        self.assertEqual(summary.error_calls, 1)
        self.assertAlmostEqual(summary.error_rate, 0.25)
        self.assertEqual(summary.read_calls, 2)
        self.assertEqual(summary.edit_calls, 1)
        self.assertEqual(summary.sessions_with_calls, 2)
        by_category = {c.category: c.calls for c in summary.categories}
        self.assertEqual(by_category[TOOL_CATEGORY_EXEC], 1)
        self.assertEqual(by_category[TOOL_CATEGORY_READ], 2)

    def test_categories_follow_fixed_order(self) -> None:
        details = [make_detail(tool_calls=(call("Read"), call("Bash"), call("Edit")))]
        summary = summarize_behavior_from_details(details)
        self.assertEqual(
            [c.category for c in summary.categories],
            [TOOL_CATEGORY_READ, TOOL_CATEGORY_EDIT, TOOL_CATEGORY_EXEC],
        )

    def test_repeats_counted_within_a_session_only(self) -> None:
        repeated = make_detail(session_id="s1", tool_calls=(call("Bash", "ls"), call("Bash", "ls"), call("Bash", "ls")))
        separate = make_detail(session_id="s2", tool_calls=(call("Bash", "ls"),))
        summary = summarize_behavior_from_details([repeated, separate])
        self.assertEqual(summary.repeated_calls, 2)
        self.assertEqual(summary.total_calls, 4)
        self.assertAlmostEqual(summary.repeat_rate, 0.5)

    def test_same_call_in_different_sessions_is_not_a_repeat(self) -> None:
        a = make_detail(session_id="s1", tool_calls=(call("Bash", "ls"),))
        b = make_detail(session_id="s2", tool_calls=(call("Bash", "ls"),))
        self.assertEqual(summarize_behavior_from_details([a, b]).repeated_calls, 0)

    def test_durations_aggregate_per_tool(self) -> None:
        details = [make_detail(tool_calls=(call("Bash", duration_ms=100), call("Bash", duration_ms=250)))]
        summary = summarize_behavior_from_details(details)
        self.assertEqual(summary.tools[0].total_duration_ms, 350)

    def test_read_write_ratio(self) -> None:
        details = [make_detail(tool_calls=(call("Read"), call("Read"), call("Read"), call("Read"), call("Edit")))]
        self.assertEqual(summarize_behavior_from_details(details).read_write_ratio, 4.0)

    def test_ratio_is_none_without_edits(self) -> None:
        details = [make_detail(tool_calls=(call("Read"),))]
        self.assertIsNone(summarize_behavior_from_details(details).read_write_ratio)

    def test_abandoned_turns_summed(self) -> None:
        details = [make_detail(abandoned_turns=2), make_detail(session_id="s2", abandoned_turns=1)]
        self.assertEqual(summarize_behavior_from_details(details).abandoned_turns, 3)

    def test_tool_limit_is_respected(self) -> None:
        calls = tuple(call(f"tool{i}") for i in range(30))
        summary = summarize_behavior_from_details([make_detail(tool_calls=calls)], tool_limit=5)
        self.assertEqual(len(summary.tools), 5)

    def test_most_used_tools_are_ranked(self) -> None:
        details = [make_detail(tool_calls=(call("Bash"), call("Bash"), call("Bash"), call("Read")))]
        summary = summarize_behavior_from_details(details)
        self.assertEqual([t.name for t in summary.tools], ["Bash", "Read"])

    def test_repeat_time_accounts_only_for_repeat_instances(self) -> None:
        details = [
            make_detail(
                session_id="s1",
                tool_calls=(call("Bash", "ls", duration_ms=100), call("Bash", "ls", duration_ms=900)),
            )
        ]
        summary = summarize_behavior_from_details(details)
        self.assertEqual(summary.repeated_duration_ms, 900)
        self.assertEqual(summary.total_duration_ms, 1000)
        self.assertEqual(summary.timed_calls, 2)
        self.assertAlmostEqual(summary.repeat_time_rate, 0.9)

    def test_repeat_time_is_none_without_durations(self) -> None:
        summary = summarize_behavior_from_details([make_detail(tool_calls=(call("Bash"), call("Bash")) )])
        self.assertEqual(summary.total_duration_ms, 0)
        self.assertIsNone(summary.repeat_time_rate)

    def test_recovery_counts_self_corrected_failures(self) -> None:
        details = [
            make_detail(
                session_id="s1",
                tool_calls=(
                    call("Bash", "build", status=TOOL_STATUS_ERROR),
                    call("Bash", "build", status=TOOL_STATUS_ERROR),
                    call("Bash", "build"),
                ),
            )
        ]
        summary = summarize_behavior_from_details(details)
        self.assertEqual(summary.recovered_errors, 2)
        self.assertAlmostEqual(summary.error_recovery_rate, 1.0)
        self.assertEqual(summary.unrecovered_errors, 0)

    def test_unrecovered_failures_stay_unrecovered(self) -> None:
        details = [
            make_detail(
                session_id="s1",
                tool_calls=(call("Bash", "build", status=TOOL_STATUS_ERROR), call("Read")),
            )
        ]
        summary = summarize_behavior_from_details(details)
        self.assertEqual(summary.recovered_errors, 0)
        self.assertAlmostEqual(summary.error_recovery_rate, 0.0)
        self.assertEqual(summary.unrecovered_errors, 1)

    def test_recovery_is_scoped_per_session(self) -> None:
        errored = make_detail(session_id="s1", tool_calls=(call("Bash", "build", status=TOOL_STATUS_ERROR),))
        fixed = make_detail(session_id="s2", tool_calls=(call("Bash", "build"),))
        summary = summarize_behavior_from_details([errored, fixed])
        self.assertEqual(summary.recovered_errors, 0)

    def test_recovery_counts_per_tool(self) -> None:
        details = [
            make_detail(
                session_id="s1",
                tool_calls=(
                    call("Bash", "make", status=TOOL_STATUS_ERROR),
                    call("Bash", "make"),
                    call("Read"),
                ),
            )
        ]
        summary = summarize_behavior_from_details(details)
        by_name = {entry.name: entry for entry in summary.tools}
        self.assertEqual(by_name["Bash"].recovered_errors, 1)
        self.assertEqual(by_name["Read"].recovered_errors, 0)


class BehaviorTakeawayTest(unittest.TestCase):
    def test_flags_repeated_work(self) -> None:
        details = [make_detail(session_id="s1", tool_calls=(call("Bash", "ls"), call("Bash", "ls")))]
        lines = summarize_behavior_takeaways(summarize_behavior_from_details(details))
        self.assertTrue(any("repeated work" in line for line in lines))

    def test_flags_high_failure_rate(self) -> None:
        calls = tuple(call("Bash", f"c{i}", status=TOOL_STATUS_ERROR) for i in range(6))
        details = [make_detail(tool_calls=calls)]
        lines = summarize_behavior_takeaways(summarize_behavior_from_details(details))
        self.assertTrue(any("failed" in line for line in lines))

    def test_flags_read_heavy_work(self) -> None:
        calls = tuple(call("Read", f"f{i}") for i in range(9)) + (call("Edit"),)
        lines = summarize_behavior_takeaways(summarize_behavior_from_details([make_detail(tool_calls=calls)]))
        self.assertTrue(any("Read-heavy" in line for line in lines))

    def test_reports_abandoned_turns(self) -> None:
        lines = summarize_behavior_takeaways(
            summarize_behavior_from_details([make_detail(tool_calls=(call("Bash"),), abandoned_turns=3)])
        )
        self.assertTrue(any("abandoned" in line for line in lines))

    def test_flags_time_spent_on_repeats(self) -> None:
        details = [
            make_detail(
                session_id="s1",
                tool_calls=(call("Bash", "ls", duration_ms=100), call("Bash", "ls", duration_ms=9900)),
            )
        ]
        lines = summarize_behavior_takeaways(summarize_behavior_from_details(details))
        self.assertTrue(any("of tool time" in line for line in lines))

    def test_flags_unresolved_failures(self) -> None:
        details = [
            make_detail(
                session_id="s1",
                tool_calls=(
                    call("Bash", "c0", status=TOOL_STATUS_ERROR),
                    call("Bash", "c1", status=TOOL_STATUS_ERROR),
                    call("Bash", "c2", status=TOOL_STATUS_ERROR),
                ),
            )
        ]
        lines = summarize_behavior_takeaways(summarize_behavior_from_details(details))
        self.assertTrue(any("never resolved" in line for line in lines))

    def test_celebrates_successful_recovery(self) -> None:
        details = [
            make_detail(
                session_id="s1",
                tool_calls=(
                    call("Bash", "c0", status=TOOL_STATUS_ERROR),
                    call("Bash", "c1", status=TOOL_STATUS_ERROR),
                    call("Bash", "c2", status=TOOL_STATUS_ERROR),
                    call("Bash", "c0"),
                    call("Bash", "c1"),
                    call("Bash", "c2"),
                ),
            )
        ]
        lines = summarize_behavior_takeaways(summarize_behavior_from_details(details))
        self.assertTrue(any("by retrying" in line for line in lines))

    def test_quiet_usage_reports_nothing(self) -> None:
        lines = summarize_behavior_takeaways(summarize_behavior_from_details([make_detail()]))
        self.assertEqual(lines, [])

    def test_measured_behavior_displaces_weak_takeaways(self) -> None:
        from codex_stats.models import InsightReport, TimeSummary

        details = [make_detail(session_id="s1", tool_calls=(call("Bash", "ls"),) * 4)]
        summary = summarize_behavior_from_details(details)
        window_summary = TimeSummary(
            label="week", sessions=1, requests=1, input_tokens=1, output_tokens=1,
            cached_input_tokens=0, reasoning_output_tokens=0, total_tokens=1, estimated_cost_usd=1.0,
            top_model=None, average_tokens_per_request=1.0, cache_ratio=0.9,
            largest_session_tokens=1, requests_per_session=1.0, median_tokens_per_session=1.0,
            median_requests_per_session=1.0, average_session_duration_minutes=1.0,
            median_session_duration_minutes=1.0, tokens_per_minute=1.0,
            project_concentration_top1_pct=0.1, project_concentration_top3_pct=0.2,
            longest_active_streak_days=1, model_switching_rate=0.0,
        )
        report = InsightReport(
            average_tokens_per_request=1.0, cache_ratio=0.9, large_session_count=0,
            possible_savings_usd=0.0, largest_session_tokens=1, suggestion="ok",
            anomalies=["a", "b", "c", "d"], recommendations=["r"],
        )
        takeaways = summarize_takeaways(summary=window_summary, insights=report, behavior=summary, max_items=3)
        self.assertLessEqual(len(takeaways), 3)
        self.assertTrue(any("repeated work" in line for line in takeaways))


class BehaviorPanelTest(unittest.TestCase):
    """display.py is the least tested module, so the panel output is pinned here."""

    def _window(self, behavior):
        from codex_stats.cli import _build_window
        from codex_stats.config import PricingConfig

        details = [make_detail(tool_calls=(call("Bash"), call("Read"), call("Read")))]
        window = _build_window(
            key="week",
            label="Week",
            description="d",
            current_details=details,
            previous_details=[],
            current_label="last 7 days",
            previous_label="previous 7 days",
            trend_days=7,
            all_details=details,
            pricing=PricingConfig(),
            now=NOW,
        )
        if behavior is not None:
            window = type(window)(**{**window.__dict__, "behavior": behavior})
        return window

    def test_panel_renders_charts_and_table(self) -> None:
        html = _format_behavior_panel(self._window(None))
        self.assertIn("Tool Behavior", html)
        self.assertIn("Calls by Category", html)
        self.assertIn("Most Used Tools", html)
        self.assertIn("Failure Detail", html)
        self.assertIn("Tool calls", html)
        self.assertIn("Bash", html)

    def test_panel_shows_empty_state_without_data(self) -> None:
        html = _format_behavior_panel(self._window(summarize_behavior_from_details([make_detail()])))
        self.assertIn("No tool calls recorded for this view.", html)

    def test_panel_does_not_break_on_zero_calls(self) -> None:
        summary = summarize_behavior_from_details([make_detail()])
        html = _format_behavior_panel(self._window(summary))
        self.assertIn("No tool calls recorded for this view.", html)

    def test_note_explains_normalization(self) -> None:
        details = [make_detail(tool_calls=(call("Bash"),))]
        summary = summarize_behavior_from_details(details)
        html = _format_behavior_panel(self._window(summary))
        self.assertIn("normalized across tools", html)

    def test_panel_shows_repeat_time_kpi(self) -> None:
        details = [
            make_detail(
                session_id="s1",
                tool_calls=(call("Bash", duration_ms=100), call("Bash", duration_ms=900)),
            )
        ]
        html = _format_behavior_panel(self._window(summarize_behavior_from_details(details)))
        self.assertIn("Repeated time", html)
        self.assertIn("90%", html)

    def test_panel_repeat_time_is_na_without_durations(self) -> None:
        summary = summarize_behavior_from_details([make_detail(tool_calls=(call("Bash"),))])
        html = _format_behavior_panel(self._window(summary))
        self.assertIn("Repeated time", html)
        self.assertIn("n/a", html)

    def test_panel_shows_recovered_column(self) -> None:
        details = [
            make_detail(
                session_id="s1",
                tool_calls=(
                    call("Bash", "build", status=TOOL_STATUS_ERROR),
                    call("Bash", "build"),
                    call("Read"),
                ),
            )
        ]
        html = _format_behavior_panel(self._window(summarize_behavior_from_details(details)))
        self.assertIn("<th>Recovered</th>", html)
        self.assertIn("<td>1</td>", html)


if __name__ == "__main__":
    unittest.main()
