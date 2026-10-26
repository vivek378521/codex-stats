"""DeepSeek Harness (dsh) session ingest.

dsh persists every session as an append-only JSONL event log under
``$DSH_HOME/sessions`` (default ``~/.dsh``), laid out as
``<project-dir>/<session-id>/session.v<N>.jsonl[.zstd]``. The current
generation is zstd-compressed by default; each zstd file is a concatenation
of independent frames (frame 1 is exactly the session header, each later
frame is one durable append batch). This module reads those logs into the
same ``SessionDetails`` shape the other sources produce.

The log records token usage but no cost, so every dsh session is priced
from the rate table rather than carrying a recorded cost.

Format authority: deepseek-harness ``docs/persistence-catalog.md`` and the
v4 session format. Sessions with a format version newer than this reader
knows are skipped rather than misparsed; a schema we cannot interpret must
cost the reader that session, not invent numbers from fields that may have
changed meaning.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from .ingest import file_edit_from_args, is_file_editing_tool, resolve_max_sessions
from .models import (
    CACHED_SEPARATE,
    TOOL_STATUS_COMPLETED,
    TOOL_STATUS_ERROR,
    TOOL_STATUS_UNKNOWN,
    FileEdit,
    SessionDetails,
    SessionRecord,
    ToolCall,
)
from .tools import make_tool_call

SOURCE_DSH = "dsh"
DSH_PROVIDER = "deepseek"

ENV_DSH_HOME = "CODEX_STATS_DSH_HOME"

# Highest session-log format version this reader understands. dsh writes
# versioned generations (``session.v4.jsonl``) and evolves them through
# adjacent migrations; a newer version may rename or repurpose the fields
# below, so it is skipped instead of half-parsed.
DSH_KNOWN_FORMAT_VERSION = 4

# The zstd frame magic, little-endian 0xFD2FB528. Used only to walk complete
# frames after a whole-file decompress fails on a torn final frame (the
# crash tolerance dsh itself documents: an interrupted writer leaves a
# partial last frame, and the complete frames before it are still valid).
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

_SESSION_FILE_NAME = re.compile(r"^session(?:\.v(\d+))?\.jsonl(\.zstd)?$")

# Reasons a turn can end without finishing its work. ``blocked`` is a live
# wait for human approval rather than an abandoned run, and ``disposed`` is
# teardown, so neither is counted as abandoned.
_ABANDONED_TURN_KINDS = frozenset({"aborted", "error"})


def dsh_sessions_dir() -> Path:
    override = os.environ.get(ENV_DSH_HOME)
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("DSH_HOME", "~/.dsh")).expanduser() / "sessions"


def dsh_zstd_available() -> bool:
    """Can this interpreter decompress the default (compressed) generation?

    Python 3.14 ships zstd in the standard library; older interpreters need
    the third-party ``zstandard`` package. When neither is present, compressed
    sessions are skipped and the coverage note says so instead of failing.
    """
    if _stdlib_zstd() is not None:
        return True
    return _zstandard_module() is not None


def _stdlib_zstd():
    try:
        from compression import zstd
    except ImportError:
        return None
    return zstd


def _zstandard_module():
    try:
        import zstandard
    except ImportError:
        return None
    return zstandard


def dsh_session_files(sessions_dir: Path) -> list[Path]:
    """The current-generation log of every session on disk, newest first.

    A session directory can retain several immutable generations
    (``session.v3.jsonl`` beside ``session.v4.jsonl``); only the numerically
    highest is read, which is the one dsh itself resumes from. Ordering uses
    file mtime so the newest sessions survive the session cap without paying
    a header parse for the whole corpus.
    """
    if not sessions_dir.is_dir():
        return []
    latest: dict[Path, tuple[int, Path]] = {}
    for project_dir in sessions_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for session_dir in project_dir.iterdir():
            if not session_dir.is_dir():
                continue
            best: tuple[int, Path] | None = None
            for candidate in session_dir.iterdir():
                if not candidate.is_file() or candidate.name == "session.lock":
                    continue
                match = _SESSION_FILE_NAME.match(candidate.name)
                if match is None:
                    continue
                generation = int(match.group(1) or 0)
                if best is None or generation > best[0]:
                    best = (generation, candidate)
            if best is not None:
                latest[session_dir] = best
    files = [path for _, path in latest.values()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def dsh_decoder_note(sessions_dir: Path) -> str | None:
    """Explain compressed sessions this interpreter cannot decode.

    Returning ``None`` when everything is readable keeps the page quiet. When
    the directory holds ``.zstd`` logs and neither stdlib zstd nor the
    ``zstandard`` package is importable, the sessions would otherwise vanish
    from every total with no clue why.
    """
    if dsh_zstd_available():
        return None
    try:
        compressed = any(path.name.endswith(".zstd") for path in dsh_session_files(sessions_dir))
    except OSError:
        return None
    if not compressed:
        return None
    return (
        "DeepSeek Harness sessions are zstd-compressed, but this Python has no zstd "
        "decoder. Install the package with `pip install zstandard` (or use Python 3.14+) "
        "to include them."
    )


def dsh_coverage(sessions_dir: Path) -> tuple[int, int]:
    """(sessions read, sessions on disk) for dsh, or (0, 0) if unavailable."""
    total = len(dsh_session_files(sessions_dir))
    if total <= 0:
        return 0, 0
    limit = resolve_max_sessions()
    return (total if not limit else min(total, limit), total)


def iter_dsh_session_details(sessions_dir: Path) -> list[SessionDetails]:
    files = dsh_session_files(sessions_dir)
    max_sessions = resolve_max_sessions()
    if max_sessions:
        # Same bound and rationale as the other sources: newest first, so the
        # windows closest to today degrade last, and the coverage note admits
        # what was dropped instead of implying the history is complete.
        files = files[:max_sessions]
    details: list[SessionDetails] = []
    for path in files:
        parsed = _parse_session_file(path)
        if parsed is not None:
            details.append(parsed)
    return details


def _read_log_text(path: Path) -> str | None:
    """Decode one session log to text, or None when it cannot be read.

    Compressed files are decompressed frame-tolerant: a clean multi-frame
    file decodes in one call; a file with a torn final frame (the crash
    signature of an interrupted writer) keeps every complete frame and drops
    only the torn tail. A file that cannot be decoded at all is skipped —
    one unreadable session must not take down the dashboard.
    """
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    if not path.name.endswith(".zstd"):
        return blob.decode("utf-8", errors="replace")
    decoded = _decompress_zstd(blob)
    if decoded is None:
        return None
    return decoded.decode("utf-8", errors="replace")


def _decompress_zstd(blob: bytes) -> bytes | None:
    zstd = _stdlib_zstd()
    if zstd is not None:
        try:
            return zstd.decompress(blob)
        except zstd.ZstdError:
            # The whole-buffer decompress refuses a torn final frame; the
            # complete frames before it are still valid data.
            return _decompress_complete_frames(zstd, blob)
    zstandard = _zstandard_module()
    if zstandard is None:
        return None
    try:
        return zstandard.ZstdDecompressor().decompressobj().decompress(blob)
    except zstandard.ZstdError:
        # No frame walker here: the stdlib path owns torn-tail recovery on
        # interpreters new enough to have it, and this fallback exists only
        # to read clean files on older ones.
        return None


def _decompress_complete_frames(zstd, blob: bytes) -> bytes | None:
    """Decode every complete zstd frame, stopping before a torn tail."""
    chunks: list[bytes] = []
    offset = 0
    while offset < len(blob):
        remaining = blob[offset:]
        if not remaining.startswith(_ZSTD_MAGIC):
            break
        try:
            size = zstd.get_frame_size(remaining)
        except zstd.ZstdError:
            # The frame header itself is incomplete: nothing more is decodable.
            break
        if size <= 0 or size > len(remaining):
            break
        try:
            chunks.append(zstd.decompress(remaining[:size]))
        except zstd.ZstdError:
            break
        offset += size
    if not chunks:
        return None
    return b"".join(chunks)


def _dt_from_unix_millis(value: object) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _parse_session_file(path: Path) -> SessionDetails | None:
    text = _read_log_text(path)
    if text is None:
        return None

    request_count = 0
    abandoned_turns = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    reasoning_tokens = 0
    model_counter: Counter[str] = Counter()
    event_times: list[int] = []
    header: dict | None = None
    pending_calls: list[dict] = []
    call_results: dict[str, tuple[bool, int | None]] = {}
    edits: list[FileEdit] = []

    def _add_usage(usage: object) -> None:
        nonlocal input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens
        if not isinstance(usage, dict):
            return
        input_tokens += _as_int(usage.get("inputTokens"))
        output_tokens += _as_int(usage.get("outputTokens"))
        cache_read_tokens += _as_int(usage.get("cacheReadTokens"))
        cache_write_tokens += _as_int(usage.get("cacheWriteTokens"))
        reasoning_tokens += _as_int(usage.get("reasoningTokens"))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if header is None:
            if event_type != "session":
                continue
            header = event
            version = event.get("version")
            if isinstance(version, int) and version > DSH_KNOWN_FORMAT_VERSION:
                # A format we have never seen: the fields below may have
                # changed meaning, so the session is skipped whole.
                return None
            continue

        time_ms = event.get("time")
        if isinstance(time_ms, int) and not isinstance(time_ms, bool):
            event_times.append(time_ms)

        data = event.get("data")
        data = data if isinstance(data, dict) else {}

        if event_type == "user/message":
            # Every user/message is input a person (or an approved reply)
            # admitted to the inbox; tool results are their own event type.
            request_count += 1
        elif event_type == "assistant/message":
            _add_usage(data.get("usage"))
            source = data.get("message", {}).get("source") if isinstance(data.get("message"), dict) else None
            if isinstance(source, dict) and isinstance(source.get("model"), str):
                model_counter[source["model"]] += 1
        elif event_type == "compaction/summary":
            # The summarization call is real spend recorded on its own event.
            _add_usage(data.get("usage"))
            if isinstance(data.get("model"), str):
                model_counter[data["model"]] += 1
        elif event_type == "request/header":
            config = data.get("header", {}).get("config") if isinstance(data.get("header"), dict) else None
            if isinstance(config, dict) and isinstance(config.get("model"), str):
                model_counter[config["model"]] += 1
        elif event_type == "tool/call":
            call_id = data.get("callId")
            if isinstance(call_id, str) and call_id:
                pending_calls.append(
                    {
                        "name": data.get("name"),
                        "arguments": data.get("arguments"),
                        "call_id": call_id,
                        "time": time_ms if isinstance(time_ms, int) else None,
                    }
                )
                name = data.get("name")
                if is_file_editing_tool(name):
                    edit = file_edit_from_args(name, data.get("arguments"))
                    if edit is not None:
                        edits.append(edit)
        elif event_type == "tool/result":
            message = data.get("message")
            message = message if isinstance(message, dict) else {}
            call_id = message.get("toolCallId")
            if isinstance(call_id, str) and call_id:
                is_error = bool(message.get("isError")) or data.get("error") is not None
                result_time = time_ms if isinstance(time_ms, int) else None
                call_results[call_id] = (is_error, result_time)
        elif event_type == "turn/end":
            reason = data.get("reason")
            kind = reason.get("kind") if isinstance(reason, dict) else None
            if kind in _ABANDONED_TURN_KINDS:
                abandoned_turns += 1

    if header is None:
        return None

    created_at = _dt_from_unix_millis(header.get("createdAt"))
    if created_at is None:
        created_at = _dt_from_unix_millis(min(event_times)) if event_times else None
    last_time = max(event_times) if event_times else header.get("createdAt")
    updated_at = _dt_from_unix_millis(last_time) or created_at
    if created_at is None or updated_at is None:
        return None

    total_tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens + reasoning_tokens
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id:
        session_id = path.parent.name
    cwd = header.get("cwd")
    session = SessionRecord(
        session_id=session_id,
        created_at=created_at,
        updated_at=updated_at,
        cwd=cwd if isinstance(cwd, str) else "",
        model=model_counter.most_common(1)[0][0] if model_counter else None,
        model_provider=DSH_PROVIDER,
        tokens_used=total_tokens,
        rollout_path=path,
        # The session log records no git branch; deriving one from the cwd at
        # read time would attribute today's branch to yesterday's spend.
        git_branch=None,
        git_origin_url=None,
        source=SOURCE_DSH,
    )
    return SessionDetails(
        session=session,
        request_count=request_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_output_tokens=reasoning_tokens or None,
        total_tokens_from_rollout=total_tokens,
        started_at=created_at,
        file_edits=tuple(edits),
        token_accounting=CACHED_SEPARATE,
        tool_calls=tuple(_dsh_tool_calls(pending_calls, call_results)),
        abandoned_turns=abandoned_turns,
    )


def _dsh_tool_calls(
    pending_calls: list[dict],
    call_results: dict[str, tuple[bool, int | None]],
) -> list[ToolCall]:
    """Resolve recorded calls against their results.

    dsh pairs every ``tool/call`` with a ``tool/result`` carrying the same
    ``callId``; a call whose result never landed (a crash between the two
    events) keeps unknown status rather than being read as a failure.
    """
    calls: list[ToolCall] = []
    for record in pending_calls:
        call_id = record.get("call_id")
        result = call_results.get(call_id) if isinstance(call_id, str) else None
        status = TOOL_STATUS_UNKNOWN
        duration_ms = None
        if result is not None:
            is_error, result_time = result
            status = TOOL_STATUS_ERROR if is_error else TOOL_STATUS_COMPLETED
            started = record.get("time")
            if isinstance(started, int) and isinstance(result_time, int):
                elapsed = result_time - started
                duration_ms = elapsed if elapsed >= 0 else None
        calls.append(
            make_tool_call(
                record.get("name"),
                record.get("arguments"),
                status=status,
                duration_ms=duration_ms,
            )
        )
    return calls
