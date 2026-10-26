from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats.config import (
    DEFAULT_FALLBACK_RATES,
    DEFAULT_MODEL_RATES,
    PricingConfig,
)
from codex_stats.dsh_ingest import (
    _decompress_zstd,
    _read_log_text,
    _stdlib_zstd,
    dsh_coverage,
    dsh_session_files,
    dsh_sessions_dir,
    dsh_zstd_available,
    iter_dsh_session_details,
)
from codex_stats.models import (
    CACHED_SEPARATE,
    TOOL_CATEGORY_AGENT,
    TOOL_CATEGORY_EDIT,
    TOOL_CATEGORY_EXEC,
    TOOL_CATEGORY_PLAN,
    TOOL_STATUS_COMPLETED,
    TOOL_STATUS_ERROR,
    TOOL_STATUS_UNKNOWN,
)
from codex_stats.sources import (
    FILE_EDIT_TRACKING_SOURCES,
    SOURCE_DSH,
    SOURCE_LABELS,
    _dsh_source,
    iter_sources,
)
from codex_stats.tools import tool_category

T0 = 1_767_225_600_000  # 2026-01-01T00:00:00Z in ms


def _event(event_type: str, data: dict, seq: int, time_ms: int, **extra) -> dict:
    payload = {"type": event_type, "seq": seq, "time": time_ms, "data": data}
    payload.update(extra)
    return payload


def _header(session_id: str = "s1", created_ms: int = T0, cwd: str = "/w/proj", version: int = 4) -> dict:
    return {
        "type": "session",
        "version": version,
        "id": session_id,
        "createdAt": created_ms,
        "cwd": cwd,
    }


def _basic_events() -> list[dict]:
    """A small but complete session: one turn, two tool calls, real usage."""
    return [
        _event("user/message", {"message": {"role": "user", "content": []}}, 1, T0 + 10),
        _event(
            "request/header",
            {"header": {"config": {"provider": "deepseek", "model": "deepseek-flash"}}, "reason": "first"},
            2,
            T0 + 20,
        ),
        _event(
            "assistant/message",
            {
                "turn": 1,
                "step": 1,
                "message": {
                    "role": "assistant",
                    "id": "m1",
                    "content": [],
                    "source": {"kind": "model", "provider": "deepseek", "model": "deepseek-flash"},
                },
                "stream": [],
                "usage": {
                    "inputTokens": 1000,
                    "outputTokens": 200,
                    "cacheReadTokens": 400,
                    "cacheWriteTokens": 50,
                    "reasoningTokens": 30,
                },
            },
            3,
            T0 + 300,
        ),
        _event(
            "tool/call",
            {"turn": 1, "step": 1, "callId": "c1", "name": "edit", "arguments": json.dumps({
                "file_path": "/w/proj/a.py",
                "old_string": "x = 1",
                "new_string": "x = 2\ny = 3",
            })},
            4,
            T0 + 310,
        ),
        _event(
            "tool/result",
            {"turn": 1, "step": 1, "message": {"role": "tool", "toolCallId": "c1", "content": [], "isError": False}},
            5,
            T0 + 410,
        ),
        _event(
            "tool/call",
            {"turn": 1, "step": 2, "callId": "c2", "name": "bash", "arguments": json.dumps({"command": "ls"})},
            6,
            T0 + 500,
        ),
        _event(
            "tool/result",
            {
                "turn": 1,
                "step": 2,
                "message": {"role": "tool", "toolCallId": "c2", "content": [], "isError": True},
                "error": {"code": "exit", "name": "ExitCodeError"},
            },
            7,
            T0 + 600,
        ),
        _event("turn/start", {"turn": 1}, 8, T0 + 90),
        _event("turn/end", {"turn": 1, "reason": {"kind": "completed"}}, 9, T0 + 700),
        _event("turn/start", {"turn": 2}, 10, T0 + 800),
        _event("turn/end", {"turn": 2, "reason": {"kind": "aborted", "reason": "user"}}, 11, T0 + 900),
    ]


def _write_session(
    root: Path,
    lines: list,
    *,
    project: str = "--w-proj--",
    session_id: str = "s1",
    generation: str = "v4",
    compressed: bool = False,
    mtime: float | None = None,
) -> Path:
    session_dir = root / project / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(line) for line in lines) + "\n"
    name = f"session.{generation}.jsonl" + (".zstd" if compressed else "")
    path = session_dir / name
    if compressed:
        zstd = _stdlib_zstd()
        if zstd is None:
            import zstandard
            path.write_bytes(zstandard.ZstdCompressor().compress(text.encode("utf-8")))
        else:
            # One frame per write batch, matching dsh's writer: frame 1 holds
            # the header, later frames hold event batches.
            frames = [zstd.compress((json.dumps(line) + "\n").encode("utf-8")) for line in lines]
            path.write_bytes(b"".join(frames))
    else:
        path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class DshIngestTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "sessions"
        self.root.mkdir(parents=True)
        self._old_env = {
            key: os.environ.get(key)
            for key in ("CODEX_STATS_DSH_HOME", "CODEX_STATS_MAX_SESSIONS", "DSH_HOME")
        }
        os.environ["CODEX_STATS_DSH_HOME"] = str(self.root)

    def tearDown(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_sessions_dir_honours_override(self) -> None:
        self.assertEqual(dsh_sessions_dir(), self.root)

    def test_missing_dir_yields_empty(self) -> None:
        self.root.rmdir()
        self.assertEqual(iter_dsh_session_details(self.root), [])
        self.assertEqual(dsh_coverage(self.root), (0, 0))
        self.assertEqual(dsh_session_files(self.root), [])

    def test_basic_session_parses(self) -> None:
        _write_session(self.root, [_header(), *_basic_events()])
        (detail,) = iter_dsh_session_details(self.root)

        self.assertEqual(detail.session.source, "dsh")
        self.assertEqual(detail.session.model_provider, "deepseek")
        self.assertEqual(detail.session.session_id, "s1")
        self.assertEqual(detail.session.cwd, "/w/proj")
        self.assertEqual(detail.session.model, "deepseek-flash")
        self.assertEqual(detail.session.created_at, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(detail.request_count, 1)
        self.assertEqual(detail.input_tokens, 1000)
        self.assertEqual(detail.output_tokens, 200)
        self.assertEqual(detail.cached_input_tokens, 400)
        self.assertEqual(detail.cache_write_tokens, 50)
        self.assertEqual(detail.reasoning_output_tokens, 30)
        self.assertEqual(detail.total_tokens_from_rollout, 1680)
        self.assertEqual(detail.token_accounting, CACHED_SEPARATE)
        self.assertEqual(detail.abandoned_turns, 1)

        self.assertEqual(len(detail.tool_calls), 2)
        edit_call, bash_call = detail.tool_calls
        self.assertEqual(edit_call.status, TOOL_STATUS_COMPLETED)
        self.assertEqual(edit_call.category, TOOL_CATEGORY_EDIT)
        self.assertEqual(edit_call.duration_ms, 100)
        self.assertEqual(bash_call.status, TOOL_STATUS_ERROR)
        self.assertEqual(bash_call.category, TOOL_CATEGORY_EXEC)
        self.assertEqual(bash_call.duration_ms, 100)

        (edit,) = detail.file_edits
        self.assertEqual(edit.path, "/w/proj/a.py")
        self.assertEqual(edit.action, "updated")
        self.assertEqual(edit.insertions, 2)
        self.assertEqual(edit.deletions, 1)

    def test_call_without_result_is_unknown(self) -> None:
        events = [
            _header(),
            _event(
                "tool/call",
                {"turn": 1, "step": 1, "callId": "c1", "name": "read", "arguments": "{}"},
                1,
                T0 + 10,
            ),
        ]
        _write_session(self.root, events)
        (detail,) = iter_dsh_session_details(self.root)
        self.assertEqual(detail.tool_calls[0].status, TOOL_STATUS_UNKNOWN)
        self.assertIsNone(detail.tool_calls[0].duration_ms)

    def test_model_dominance_prefers_header_and_source(self) -> None:
        events = [_header()]
        for index, model in enumerate(("deepseek-flash", "deepseek-v4-pro", "deepseek-flash"), start=1):
            events.append(
                _event(
                    "request/header",
                    {"header": {"config": {"provider": "deepseek", "model": model}}, "reason": "switch"},
                    index * 2,
                    T0 + index,
                )
            )
        _write_session(self.root, events)
        (detail,) = iter_dsh_session_details(self.root)
        self.assertEqual(detail.session.model, "deepseek-flash")

    def test_compaction_usage_is_summed(self) -> None:
        events = [
            _header(),
            _event(
                "compaction/summary",
                {
                    "compactionId": "k1",
                    "turn": 1,
                    "model": "deepseek-flash",
                    "summary": [],
                    "usage": {"inputTokens": 10, "outputTokens": 5},
                },
                1,
                T0 + 10,
            ),
        ]
        _write_session(self.root, events)
        (detail,) = iter_dsh_session_details(self.root)
        self.assertEqual(detail.input_tokens, 10)
        self.assertEqual(detail.output_tokens, 5)
        self.assertEqual(detail.request_count, 0)

    def test_future_format_version_is_skipped(self) -> None:
        _write_session(self.root, [_header(version=5), *_basic_events()])
        self.assertEqual(iter_dsh_session_details(self.root), [])

    def test_latest_generation_wins(self) -> None:
        _write_session(
            self.root,
            [_header(), _event("user/message", {"message": {}}, 1, T0 + 10)],
            generation="v3",
        )
        _write_session(self.root, [_header(), *_basic_events()], generation="v4")
        (detail,) = iter_dsh_session_details(self.root)
        self.assertEqual(detail.request_count, 1)
        self.assertEqual(detail.session.rollout_path.name, "session.v4.jsonl")

    def test_corrupt_lines_are_tolerated(self) -> None:
        session_dir = self.root / "--w-proj--" / "s1"
        session_dir.mkdir(parents=True)
        path = session_dir / "session.v4.jsonl"
        body = "\n".join(json.dumps(line) for line in [_header(), *_basic_events()])
        path.write_text("{not json\n" + body + "\ntrailing garbage\n", encoding="utf-8")
        (detail,) = iter_dsh_session_details(self.root)
        self.assertEqual(detail.request_count, 1)

    def test_session_cap_keeps_newest(self) -> None:
        _write_session(
            self.root,
            [_header(session_id="old"), *_basic_events()],
            session_id="old",
            mtime=1_000,
        )
        _write_session(
            self.root,
            [_header(session_id="new"), *_basic_events()],
            session_id="new",
            mtime=2_000,
        )
        os.environ["CODEX_STATS_MAX_SESSIONS"] = "1"
        details = iter_dsh_session_details(self.root)
        self.assertEqual([d.session.session_id for d in details], ["new"])
        self.assertEqual(dsh_coverage(self.root), (1, 2))

    @unittest.skipUnless(dsh_zstd_available(), "no zstd decompressor available")
    def test_compressed_session_parses(self) -> None:
        _write_session(self.root, [_header(), *_basic_events()], compressed=True)
        (detail,) = iter_dsh_session_details(self.root)
        self.assertEqual(detail.request_count, 1)
        self.assertEqual(detail.input_tokens, 1000)
        self.assertEqual(len(detail.tool_calls), 2)

    @unittest.skipUnless(_stdlib_zstd() is not None, "stdlib zstd required for torn-tail recovery")
    def test_torn_zstd_tail_keeps_complete_frames(self) -> None:
        zstd = _stdlib_zstd()
        session_dir = self.root / "--w-proj--" / "s1"
        session_dir.mkdir(parents=True)
        frame1 = zstd.compress((json.dumps(_header()) + "\n").encode("utf-8"))
        frame2 = zstd.compress((json.dumps(_event("user/message", {"message": {}}, 1, T0 + 10)) + "\n").encode("utf-8"))
        path = session_dir / "session.v4.jsonl.zstd"
        # Truncate inside frame 2: the crash signature of an interrupted writer.
        path.write_bytes(frame1 + frame2[: len(frame2) // 2])
        (detail,) = iter_dsh_session_details(self.root)
        self.assertEqual(detail.request_count, 0)
        self.assertEqual(detail.session.session_id, "s1")

    @unittest.skipUnless(dsh_zstd_available(), "no zstd decompressor available")
    def test_undecodable_zstd_is_skipped(self) -> None:
        session_dir = self.root / "--w-proj--" / "s1"
        session_dir.mkdir(parents=True)
        (session_dir / "session.v4.jsonl.zstd").write_bytes(b"not a zstd stream at all")
        self.assertEqual(iter_dsh_session_details(self.root), [])

    def test_lock_file_and_stray_files_ignored(self) -> None:
        _write_session(self.root, [_header(), *_basic_events()])
        session_dir = self.root / "--w-proj--" / "s1"
        (session_dir / "session.lock").write_text("", encoding="utf-8")
        (session_dir / "notes.txt").write_text("hi", encoding="utf-8")
        files = dsh_session_files(self.root)
        self.assertEqual([path.name for path in files], ["session.v4.jsonl"])

    def test_header_only_session_is_valid(self) -> None:
        _write_session(self.root, [_header()])
        (detail,) = iter_dsh_session_details(self.root)
        self.assertEqual(detail.request_count, 0)
        self.assertEqual(detail.total_tokens_from_rollout, 0)
        self.assertEqual(detail.session.created_at, datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_missing_header_returns_none(self) -> None:
        _write_session(self.root, [_event("user/message", {"message": {}}, 1, T0 + 10)])
        self.assertEqual(iter_dsh_session_details(self.root), [])


class DshRegistrationTest(unittest.TestCase):
    def test_source_is_registered(self) -> None:
        source = _dsh_source()
        self.assertEqual(source.key, SOURCE_DSH)
        self.assertEqual(source.label, "DeepSeek Harness")
        self.assertIn(SOURCE_DSH, SOURCE_LABELS)
        self.assertIn(SOURCE_DSH, FILE_EDIT_TRACKING_SOURCES)

    def test_iter_sources_includes_dsh(self) -> None:
        keys = [source.key for source in iter_sources()]
        self.assertIn(SOURCE_DSH, keys)


class DshTaxonomyTest(unittest.TestCase):
    def test_dsh_tool_names_map_to_categories(self) -> None:
        cases = {
            "bash": TOOL_CATEGORY_EXEC,
            "pwsh": TOOL_CATEGORY_EXEC,
            "terminal_read": TOOL_CATEGORY_EXEC,
            "terminal_open": TOOL_CATEGORY_EXEC,
            "job_list": TOOL_CATEGORY_EXEC,
            "todo_write": TOOL_CATEGORY_PLAN,
            "create_goal": TOOL_CATEGORY_PLAN,
            "exit_plan_mode": TOOL_CATEGORY_PLAN,
            "send_message": TOOL_CATEGORY_AGENT,
            "subagent": TOOL_CATEGORY_AGENT,
            "edit": TOOL_CATEGORY_EDIT,
            "write": TOOL_CATEGORY_EDIT,
            "str_replace_editor": TOOL_CATEGORY_EDIT,
        }
        for name, category in cases.items():
            self.assertEqual(tool_category(name), category, name)


class DeepSeekPricingTest(unittest.TestCase):
    def test_known_models_are_not_fallback(self) -> None:
        config = PricingConfig()
        for model in ("deepseek-flash", "deepseek-chat", "deepseek-v4-pro"):
            rates, is_fallback = config.rates_for("dsh", model)
            self.assertFalse(is_fallback, model)
            self.assertIn(rates, DEFAULT_MODEL_RATES.values())

    def test_flash_rates(self) -> None:
        config = PricingConfig()
        rates, _ = config.rates_for("dsh", "deepseek-flash")
        self.assertAlmostEqual(rates.input_usd_per_1k, 0.00015)
        self.assertAlmostEqual(rates.cached_read_usd_per_1k, 0.000003)
        self.assertEqual(rates.cache_write_usd_per_1k, 0.0)
        self.assertAlmostEqual(rates.output_usd_per_1k, 0.0006)

    def test_unknown_deepseek_model_falls_back(self) -> None:
        config = PricingConfig()
        rates, is_fallback = config.rates_for("dsh", "deepseek-mystery-model")
        self.assertTrue(is_fallback)
        self.assertEqual(rates, DEFAULT_FALLBACK_RATES)


class ZstdHelperTest(unittest.TestCase):
    def test_decompress_none_for_garbage(self) -> None:
        self.assertIsNone(_decompress_zstd(b"garbage without magic"))

    def test_read_plain_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.v4.jsonl"
            path.write_text('{"type":"session"}\n', encoding="utf-8")
            self.assertEqual(_read_log_text(path), '{"type":"session"}\n')


if __name__ == "__main__":
    unittest.main()
