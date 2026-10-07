from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .config import Paths
from .ingest import (
    codex_session_coverage,
    file_edit_from_args,
    is_file_editing_tool,
    iter_session_details as _codex_iter_session_details,
    resolve_max_sessions,
)
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

SOURCE_CODEX = "codex"
SOURCE_OPENCODE = "opencode"
SOURCE_CLAUDE = "claude"
SOURCE_HERMES = "hermes"

CLAUDE_PROVIDER = "anthropic"
HERMES_PROVIDER = "hermes"
OPENCODE_PROVIDER = "opencode"

# Claude Code's session-control tools record an ``is_error`` result when the user-flow is
# cancelled or declined (a question dismissed, a plan rejected), which is not a command
# failure. Reading those as errors would poison the failure rate with interaction noise.
_CLAUDE_CONTROL_TOOLS = frozenset({"AskUserQuestion", "ExitPlanMode"})


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    description: str
    available: bool
    path_hint: str
    ingest: Callable[[], list[SessionDetails]] = field(repr=False, compare=False)
    coverage: Callable[[], tuple[int, int]] = field(
        repr=False,
        compare=False,
        default=lambda: (0, 0),
    )


def _codex_source(paths: Paths | None = None) -> Source:
    paths = paths or Paths.discover()
    return Source(
        key=SOURCE_CODEX,
        label="Codex",
        description="OpenAI Codex CLI sessions from the local ~/.codex state database and rollout files.",
        available=paths.state_db.exists(),
        path_hint=str(paths.codex_home),
        ingest=lambda: _codex_iter_session_details(paths),
        coverage=lambda: codex_session_coverage(paths),
    )


def _opencode_root() -> Path:
    override = os.environ.get("CODEX_STATS_OPENCODE_HOME")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME", "~/.local/share")).expanduser()
    return base / "opencode"


def _opencode_source(paths: Paths | None = None) -> Source:
    root = _opencode_root()
    db_path = root / "opencode.db"
    return Source(
        key=SOURCE_OPENCODE,
        label="OpenCode",
        description="Local opencode sessions from the opencode.db database, which records cost and token usage directly.",
        available=db_path.exists(),
        path_hint=str(root),
        ingest=lambda: _ingest_opencode(db_path),
        coverage=lambda: _opencode_coverage(db_path),
    )


def _claude_projects_dir() -> Path:
    override = os.environ.get("CODEX_STATS_CLAUDE_PROJECTS_DIR")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser() / "projects"


def _claude_source(paths: Paths | None = None) -> Source:
    projects_dir = _claude_projects_dir()
    return Source(
        key=SOURCE_CLAUDE,
        label="Claude Code",
        description="Claude Code sessions read from the per-project JSONL transcripts under ~/.claude/projects.",
        available=bool(projects_dir.exists() and any(projects_dir.glob("*"))),
        path_hint=str(projects_dir),
        ingest=lambda: _ingest_claude(projects_dir),
        coverage=lambda: _claude_coverage(projects_dir),
    )


def _hermes_home() -> Path:
    override = os.environ.get("CODEX_STATS_HERMES_HOME")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()


def _hermes_source(paths: Paths | None = None) -> Source:
    home = _hermes_home()
    state_db = home / "state.db"
    return Source(
        key=SOURCE_HERMES,
        label="Hermes",
        description="Hermes agent sessions from the local ~/.hermes/state.db, which records per-session token usage.",
        available=state_db.exists(),
        path_hint=str(home),
        ingest=lambda: _ingest_hermes(state_db),
        coverage=lambda: _hermes_coverage(state_db),
    )


_SOURCE_FACTORIES: list[Callable[[Paths], Source]] = [
    _codex_source,
    _opencode_source,
    _claude_source,
    _hermes_source,
]

SOURCE_LABELS: dict[str, str] = {
    SOURCE_CODEX: "Codex",
    SOURCE_OPENCODE: "OpenCode",
    SOURCE_CLAUDE: "Claude Code",
    SOURCE_HERMES: "Hermes",
}

# The sources whose transcripts name the files a session edited. OpenCode and
# Hermes record tokens and cost but nothing about files, so they are deliberately
# absent: dividing their spend by lines changed would divide by zero, and treating
# their sessions as read-only would invent a finding the data cannot support. Any
# metric that joins spend to work has to gate on this rather than deriving the
# answer from an absence of edits, which is indistinguishable from a session that
# genuinely changed nothing.
FILE_EDIT_TRACKING_SOURCES = frozenset({SOURCE_CODEX, SOURCE_CLAUDE})


def iter_sources(paths: Paths | None = None) -> list[Source]:
    return [factory(paths) for factory in _SOURCE_FACTORIES]


def source_label(source_key: str) -> str:
    return SOURCE_LABELS.get(source_key, source_key.capitalize())


def _dt_from_unix_seconds(value: float | int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)


def _dt_from_unix_millis(value: float | int | None) -> datetime | None:
    """Convert a millisecond epoch column, treating NULL as unusable.

    A NULL is a real possibility here rather than a theoretical one: the query
    filters on ``time_updated`` only, so a row with a created stamp but no updated
    one still reaches this loop. Dividing before the None check raises TypeError
    and kills ingest for every source, which is why the conversion is guarded
    before any arithmetic happens.
    """
    if value is None:
        return None
    try:
        return _dt_from_unix_seconds(value / 1000)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _dt_from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _as_int(value) -> int:
    return int(value or 0)


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetchall(connection: sqlite3.Connection, query: str, parameters: tuple = ()) -> list[sqlite3.Row]:
    """Run a read, degrading to no rows when the schema has drifted.

    One unreadable source must not take down the dashboard for the other three.
    The user still gets every tool that *can* be read, and the missing one renders
    as an empty state, which is the honest outcome: a tool that has drifted and a
    tool that was never installed are both "no data here", and neither should cost
    the reader the other three.
    """
    try:
        if parameters:
            return connection.execute(query, parameters).fetchall()
        return connection.execute(query).fetchall()
    except sqlite3.Error:
        return []


def _chunks(values: set[str], size: int = 500) -> list[list[str]]:
    """Slice an id set into IN-lists that stay under SQLite's variable limit.

    The session cap can run to thousands of ids, and SQLite binds at most 999
    variables per statement, so a single ``IN (...`` for the whole set would raise
    when the cap is unset. Chunking keeps the query well under the limit.
    """
    ordered = list(values)
    return [ordered[index:index + size] for index in range(0, len(ordered), size)]


def _placeholders(count: int) -> str:
    return ",".join("?" for _ in range(count))


def _bounded_coverage(total: int) -> tuple[int, int]:
    """Apply the session cap to a session total already known to disk.

    The cap is pure arithmetic once the total is known, so this reports what the
    ingest will read without re-running it.
    """
    if total <= 0:
        return 0, 0
    limit = resolve_max_sessions()
    return (total if not limit else min(total, limit), total)


def _count_sqlite(db_path: Path, query: str) -> int:
    """Count rows for the coverage note, tolerating a missing or changed schema.

    Coverage is disclosure, not data: a database that cannot be counted must not
    stop the dashboard from rendering, so every failure degrades to "unknown"
    and the source stays silent rather than claiming a complete history.
    """
    if not db_path.exists():
        return 0
    try:
        connection = _connect_sqlite(db_path)
    except sqlite3.Error:
        return 0
    try:
        return int(connection.execute(query).fetchone()[0])
    except (sqlite3.Error, TypeError, IndexError):
        return 0
    finally:
        connection.close()


def _claude_coverage(projects_dir: Path) -> tuple[int, int]:
    if not projects_dir.is_dir():
        return 0, 0
    return _bounded_coverage(
        sum(1 for project_dir in projects_dir.iterdir() if project_dir.is_dir() for _ in project_dir.glob("*.jsonl"))
    )


def _opencode_coverage(db_path: Path) -> tuple[int, int]:
    return _bounded_coverage(_count_sqlite(db_path, "SELECT COUNT(*) FROM session WHERE time_updated > 0"))


def _hermes_coverage(state_db: Path) -> tuple[int, int]:
    return _bounded_coverage(_count_sqlite(state_db, "SELECT COUNT(*) FROM sessions WHERE started_at > 0"))


def _ingest_opencode(db_path: Path) -> list[SessionDetails]:
    if not db_path.exists():
        return []
    connection = _connect_sqlite(db_path)
    details: list[SessionDetails] = []
    try:
        query = """
            SELECT
                id,
                directory,
                model,
                cost,
                tokens_input,
                tokens_output,
                tokens_reasoning,
                tokens_cache_read,
                tokens_cache_write,
                time_created,
                time_updated,
                summary_files,
                summary_additions,
                summary_deletions,
                summary_diffs
            FROM session
            WHERE time_updated > 0
            ORDER BY time_updated DESC
            """
        max_sessions = resolve_max_sessions()
        if max_sessions:
            # Safe to push into SQL: the ordering above is already newest first, so
            # the limit keeps the most recent sessions and drops the oldest. This is
            # the same bound Codex applies, and the coverage note reports what it drops.
            query += f"\n            LIMIT {max_sessions}"
        rows = _fetchall(connection, query)
        selected_ids = {row["id"] for row in rows}
        # Restrict both reads below to the capped session set inside SQL. The session
        # cap bounds which sessions matter, but message and part tables have no cap
        # of their own, so without an explicit IN the whole history of both tables is
        # pulled and filtered in Python on every launch.
        request_counts = {} if rows else {}
        for chunk in _chunks(selected_ids):
            request_counts.update(
                {
                    row["session_id"]: row["count"]
                    for row in _fetchall(
                        connection,
                        """
                        SELECT session_id, COUNT(*) AS count
                        FROM message
                        WHERE session_id IN (%s)
                          AND json_extract(data, '$.role') = 'user'
                        GROUP BY session_id
                        """ % _placeholders(len(chunk)),
                        chunk,
                    )
                }
            )
        tool_calls = _opencode_tool_calls(connection, selected_ids)
    finally:
        connection.close()

    for row in rows:
        # Convert before calling the guard, not after: dividing a NULL column raises
        # TypeError, which is not caught here and would take down every tab rather
        # than skipping the one unusable row. A session the tool cannot date cannot
        # be placed in any window, so it is skipped instead.
        created_at = _dt_from_unix_millis(row["time_created"])
        updated_at = _dt_from_unix_millis(row["time_updated"])
        if created_at is None or updated_at is None:
            continue
        input_tokens = _as_int(row["tokens_input"])
        output_tokens = _as_int(row["tokens_output"])
        reasoning_tokens = _as_int(row["tokens_reasoning"])
        cache_read_tokens = _as_int(row["tokens_cache_read"])
        cache_write_tokens = _as_int(row["tokens_cache_write"])
        total_tokens = input_tokens + output_tokens + reasoning_tokens + cache_read_tokens + cache_write_tokens
        model = _opencode_model_name(row["model"])
        session = SessionRecord(
            session_id=row["id"],
            created_at=created_at,
            updated_at=updated_at,
            cwd=row["directory"] or "",
            model=model,
            model_provider=OPENCODE_PROVIDER,
            tokens_used=total_tokens,
            rollout_path=db_path,
            git_branch=None,
            git_origin_url=None,
            source=SOURCE_OPENCODE,
        )
        details.append(
            SessionDetails(
                session=session,
                request_count=request_counts.get(row["id"], 0),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=_as_int(row["tokens_cache_read"]),
                cache_write_tokens=_as_int(row["tokens_cache_write"]),
                reasoning_output_tokens=reasoning_tokens,
                total_tokens_from_rollout=total_tokens,
                started_at=created_at,
                recorded_cost_usd=_as_float(row["cost"]),
                token_accounting=CACHED_SEPARATE,
                tool_calls=tuple(tool_calls.get(row["id"], ())),
                opencode_summary=_opencode_file_summary(row),
            )
        )
    return details


def _opencode_file_summary(row: sqlite3.Row) -> tuple[int, int, int, int] | None:
    """The file-change totals OpenCode can record instead of per-file edits.

    OpenCode's schema carries ``summary_files``, ``summary_additions``,
    ``summary_deletions``, and ``summary_diffs`` as session-level totals. When the
    database populates them the totals belong on the session; when the columns are
    zero, the source is "did not record" rather than "changed nothing", so they are
    omitted and the drilldown stays honest about the gap.
    """
    files = _as_int(row["summary_files"])
    additions = _as_int(row["summary_additions"])
    deletions = _as_int(row["summary_deletions"])
    diffs = _as_int(row["summary_diffs"])
    if not any((files, additions, deletions, diffs)):
        return None
    return (files, additions, deletions, diffs)


def _opencode_tool_calls(
    connection: sqlite3.Connection,
    session_ids: set[str],
) -> dict[str, list[ToolCall]]:
    """Read per-session tool calls out of the ``part`` table.

    OpenCode records every tool invocation as a JSON part, which makes it the richest
    source of the four: it carries an explicit status and start/end timestamps.
    """
    if not session_ids:
        return {}
    calls: dict[str, list[ToolCall]] = {}
    for chunk in _chunks(session_ids):
        numbered = _placeholders(len(chunk))
        try:
            # Filter by session in SQL first: the table is keyed by session_id (the
            # index makes that cheap), and only the capped session ids are wanted.
            # Reading every ``tool`` part in the whole table and discarding most of
            # it in Python was the original unbounded read in this source.
            rows = _fetchall(
                connection,
                "SELECT session_id, data FROM part "
                "WHERE session_id IN (%s) AND json_extract(data, '$.type') = 'tool'" % numbered,
                tuple(chunk),
            )
        except sqlite3.OperationalError:
            # A single malformed JSON row makes json_extract raise; fall back to
            # scanning the table and parsing each blob in Python so one corrupt part
            # cannot take down the whole dashboard. See roadmap: source parsing
            # resilience.
            rows = _fetchall(
                connection,
                "SELECT session_id, data FROM part WHERE session_id IN (%s)" % numbered,
                tuple(chunk),
            )
            parsed_rows: list = []
            for row in rows:
                try:
                    part = json.loads(row["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(part, dict) and part.get("type") == "tool":
                    parsed_rows.append(row)
            rows = parsed_rows
        for row in rows:
            session_id = row["session_id"]
            if session_id not in session_ids:
                continue
            try:
                part = json.loads(row["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(part, dict):
                continue
            state = part.get("state")
            state = state if isinstance(state, dict) else {}
            arguments = state.get("input")
            calls.setdefault(session_id, []).append(
                make_tool_call(
                    part.get("tool"),
                    arguments,
                    status=_opencode_tool_status(state.get("status")),
                    duration_ms=_opencode_tool_duration_ms(state.get("time")),
                )
            )
    return calls


def _opencode_tool_status(raw: object) -> str:
    if not isinstance(raw, str):
        return TOOL_STATUS_UNKNOWN
    lowered = raw.lower()
    if lowered == "error":
        return TOOL_STATUS_ERROR
    if lowered in ("completed", "success"):
        return TOOL_STATUS_COMPLETED
    return TOOL_STATUS_UNKNOWN


def _opencode_tool_duration_ms(raw: object) -> int | None:
    if not isinstance(raw, dict):
        return None
    start = _as_int(raw.get("start"))
    end = _as_int(raw.get("end"))
    if not start or not end or end < start:
        return None
    return end - start


def _opencode_model_name(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(parsed, dict):
        return parsed.get("id") or parsed.get("modelID")
    return None


def _ingest_claude(projects_dir: Path) -> list[SessionDetails]:
    if not projects_dir.is_dir():
        return []
    candidates = [path for project_dir in sorted(projects_dir.iterdir()) if project_dir.is_dir() for path in project_dir.glob("*.jsonl")]
    # Same bound as Codex, applied before parsing rather than after: transcripts
    # are the other unbounded read here, and picking the newest files by mtime is
    # far cheaper than parsing everything and sorting the results.
    max_sessions = resolve_max_sessions()
    if max_sessions:
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        candidates = candidates[:max_sessions]
    grouped: dict[str, SessionDetails] = {}
    for path in sorted(candidates):
        details = _parse_claude_session(path)
        if details is None:
            continue
        existing = grouped.get(details.session.session_id)
        if existing is None:
            grouped[details.session.session_id] = details
        elif details.session.updated_at >= existing.session.updated_at:
            grouped[details.session.session_id] = details
    ordered = sorted(grouped.values(), key=lambda detail: detail.session.updated_at, reverse=True)
    return ordered


# Claude Code writes "HEAD" when the checkout is detached. That is a real state worth
# knowing about, but it is not a workstream, and ranking it in a branch table would
# invent a branch called HEAD out of whatever was committed to at a commit rather than
# a line of work. Detached sessions are simply reported as having no branch.
_DETACHED_BRANCH_NAMES = {"head", "(detached)", "detached"}


def _normalize_git_branch(value: str) -> str | None:
    branch = value.strip()
    if not branch or branch.lower() in _DETACHED_BRANCH_NAMES:
        return None
    return branch


def _is_user_request(event: dict) -> bool:
    """Is this a ``user`` event a person actually typed?

    Claude Code writes most of its ``user`` events for itself: a ``tool_result``
    block feeds the agent's last tool call back to it, and a plain ``[Request
    interrupted...]`` text notes the user stopped a run. Neither is a request, and
    counting them would inflate "requests" and "tokens per request" next to the
    other sources, which only count real user turns. A real request has either a
    plain-string content (Claude Code writes short prompts as a bare string) or a
    ``text`` block that is not an interruption marker.
    """
    message = event.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        blocks = [block for block in content if isinstance(block, dict)]
        if not blocks:
            return False
        if all(block.get("type") == "tool_result" for block in blocks):
            return False
        if any(block.get("type") == "text" for block in blocks):
            return not any(
                isinstance(block.get("text"), str) and "interrupted" in block["text"].lower()
                for block in blocks
            )
        return False
    return False


def _parse_claude_session(path: Path) -> SessionDetails | None:
    timestamps: list[str] = []
    user_count = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    model_counter: Counter[str] = Counter()
    branch_counter: Counter[str] = Counter()
    cwd: str | None = None
    edits: list[FileEdit] = []
    pending_calls: list[dict] = []
    call_results: dict[str, bool] = {}
    call_times: dict[str, datetime] = {}
    result_times: dict[str, datetime] = {}
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            timestamp = event.get("timestamp")
            if isinstance(timestamp, str):
                timestamps.append(timestamp)
            if not cwd and isinstance(event.get("cwd"), str) and event["cwd"]:
                cwd = event["cwd"]
            # A session can span a branch switch, so the branch is counted rather
            # than taken from the first or last line, and the dominant one wins the
            # same way the dominant model does. Sessions that never switched are
            # unaffected, and a switched session is attributed to wherever most of
            # its events landed instead of to whichever end happened to come last.
            if isinstance(event.get("gitBranch"), str):
                branch = _normalize_git_branch(event["gitBranch"])
                if branch:
                    branch_counter[branch] += 1
            event_type = event.get("type")
            if event_type == "user" and _is_user_request(event):
                user_count += 1
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if event_type == "assistant" and isinstance(usage, dict):
                input_tokens += _as_int(usage.get("input_tokens"))
                output_tokens += _as_int(usage.get("output_tokens"))
                cache_read_tokens += _as_int(usage.get("cache_read_input_tokens"))
                cache_write_tokens += _as_int(usage.get("cache_creation_input_tokens"))
            if event_type == "assistant" and isinstance(message.get("model"), str):
                model_counter[message["model"]] += 1
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "tool_use":
                    tool_name = block.get("name")
                    tool_input = block.get("input")
                    use_id = block.get("id")
                    if isinstance(use_id, str):
                        pending_calls.append(
                            {"name": tool_name, "arguments": tool_input, "call_id": use_id}
                        )
                        started = _dt_from_iso(timestamp) if isinstance(timestamp, str) else None
                        if started is not None:
                            call_times[use_id] = started
                    if is_file_editing_tool(tool_name) and isinstance(tool_input, dict):
                        edits.extend(_claude_edits_from_tool_use(tool_name, tool_input))
                elif block_type == "tool_result":
                    use_id = block.get("tool_use_id")
                    if isinstance(use_id, str):
                        call_results[use_id] = bool(block.get("is_error"))
                        finished = _dt_from_iso(timestamp) if isinstance(timestamp, str) else None
                        if finished is not None:
                            result_times[use_id] = finished

    if not timestamps:
        return None
    created_at = _dt_from_iso(sorted(timestamps)[0])
    updated_at = _dt_from_iso(sorted(timestamps)[-1])
    if created_at is None or updated_at is None:
        return None
    total_tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    session = SessionRecord(
        session_id=path.stem,
        created_at=created_at,
        updated_at=updated_at,
        cwd=cwd or _decode_claude_project_path(path.parent.name),
        model=model_counter.most_common(1)[0][0] if model_counter else None,
        model_provider=CLAUDE_PROVIDER,
        tokens_used=total_tokens,
        rollout_path=path,
        git_branch=branch_counter.most_common(1)[0][0] if branch_counter else None,
        git_origin_url=None,
        source=SOURCE_CLAUDE,
    )
    return SessionDetails(
        session=session,
        request_count=user_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_output_tokens=None,
        total_tokens_from_rollout=total_tokens,
        started_at=created_at,
        file_edits=tuple(edits),
        token_accounting=CACHED_SEPARATE,
        tool_calls=tuple(_claude_tool_calls(pending_calls, call_results, call_times, result_times)),
    )


def _claude_tool_calls(
    pending_calls: list[dict],
    call_results: dict[str, bool],
    call_times: dict[str, datetime],
    result_times: dict[str, datetime],
) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for record in pending_calls:
        call_id = record.get("call_id")
        is_error = call_results.get(call_id) if isinstance(call_id, str) else None
        if is_error and record.get("name") in _CLAUDE_CONTROL_TOOLS:
            # A cancelled question or rejected plan is user-flow noise, not a tool failure.
            is_error = None
        status = (
            TOOL_STATUS_UNKNOWN
            if is_error is None
            else TOOL_STATUS_ERROR if is_error else TOOL_STATUS_COMPLETED
        )
        calls.append(
            make_tool_call(
                record.get("name"),
                record.get("arguments"),
                status=status,
                duration_ms=_claude_call_duration_ms(
                    call_times.get(call_id), result_times.get(call_id)
                )
                if isinstance(call_id, str)
                else None,
            )
        )
    return calls


def _claude_call_duration_ms(started: datetime | None, finished: datetime | None) -> int | None:
    """Time between issuing a tool call and its result arriving.

    Claude Code stamps every transcript event, and a call's result lands on a later
    ``user`` event. A call whose result never appears in the transcript gets no duration
    rather than being attributed the rest of the session, which would inflate totals.
    """
    if started is None or finished is None:
        return None
    elapsed = (finished - started).total_seconds() * 1000
    return int(elapsed) if elapsed >= 0 else None


def _claude_edits_from_tool_use(tool_name: object, tool_input: dict) -> list[FileEdit]:
    if str(tool_name).lower() in ("multiedit", "multi_edit", "multi-edit"):
        file_path = _edit_path_from_tool_input(tool_input)
        edits: list[FileEdit] = []
        sub_edits = tool_input.get("edits")
        if isinstance(sub_edits, list):
            for sub in sub_edits:
                if not isinstance(sub, dict):
                    continue
                sub_args = {
                    "file_path": file_path,
                    "old_string": sub.get("old_string"),
                    "new_string": sub.get("new_string"),
                }
                edit = file_edit_from_args(tool_name, sub_args)
                if edit is not None:
                    edits.append(edit)
        # The parent MultiEdit input has file_path plus an ``edits`` array and no
        # line text of its own, so running the parent through the ordinary parser
        # falls through to a phantom 1-insertion edit that doubles as "a file was
        # touched" once per MultiEdit call. The sub-edits above are the real work.
        return edits
    edit = file_edit_from_args(tool_name, tool_input)
    return [edit] if edit is not None else []


def _edit_path_from_tool_input(tool_input: dict) -> str | None:
    for key in ("file_path", "filepath", "path", "file"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _decode_claude_project_path(encoded: str) -> str:
    decoded = encoded.replace("-", "/")
    return decoded if decoded.startswith("/") else f"/{decoded}"


def _ingest_hermes(state_db: Path) -> list[SessionDetails]:
    if not state_db.exists():
        return []
    connection = _connect_sqlite(state_db)
    details: list[SessionDetails] = []
    try:
        query = """
            SELECT
                id,
                cwd,
                git_branch,
                git_repo_root,
                model,
                message_count,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_write_tokens,
                reasoning_tokens,
                estimated_cost_usd,
                started_at,
                ended_at,
                last_activity_at,
                display_name,
                title,
                compression_ineffective_count
            FROM sessions
            WHERE started_at > 0
            ORDER BY started_at DESC
            """
        max_sessions = resolve_max_sessions()
        if max_sessions:
            # Same bound and rationale as Codex: the ordering is already newest first,
            # so the limit drops the oldest sessions and the coverage note says so.
            query += f"\n            LIMIT {max_sessions}"
        rows = _fetchall(connection, query)
        tool_calls = _hermes_tool_calls(connection, {row["id"] for row in rows})
    finally:
        connection.close()

    for row in rows:
        created_at = _dt_from_unix_seconds(row["started_at"])
        if created_at is None:
            continue
        ended_at = _dt_from_unix_seconds(
            row["ended_at"] or row["last_activity_at"] or row["started_at"]
        )
        ended = ended_at if ended_at and ended_at >= created_at else created_at
        input_tokens = _as_int(row["input_tokens"])
        output_tokens = _as_int(row["output_tokens"])
        cache_read_tokens = _as_int(row["cache_read_tokens"])
        cache_write_tokens = _as_int(row["cache_write_tokens"])
        reasoning_tokens = _as_int(row["reasoning_tokens"])
        total_tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens + reasoning_tokens
        cwd = row["cwd"] or row["git_repo_root"] or ""
        name = row["display_name"] or row["title"] or "hermes"
        session = SessionRecord(
            session_id=row["id"],
            created_at=created_at,
            updated_at=ended,
            cwd=cwd or name,
            model=row["model"] or None,
            model_provider=HERMES_PROVIDER,
            tokens_used=total_tokens,
            rollout_path=state_db,
            git_branch=row["git_branch"] or None,
            git_origin_url=None,
            source=SOURCE_HERMES,
        )
        details.append(
            SessionDetails(
                session=session,
                request_count=_as_int(row["message_count"]),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                reasoning_output_tokens=reasoning_tokens,
                total_tokens_from_rollout=total_tokens,
                started_at=created_at,
                recorded_cost_usd=_as_float(row["estimated_cost_usd"]),
                token_accounting=CACHED_SEPARATE,
                tool_calls=tuple(tool_calls.get(row["id"], ())),
                compression_ineffective_count=_as_int(row["compression_ineffective_count"]) or None,
            )
        )
    return details


def _hermes_tool_calls(
    connection: sqlite3.Connection,
    session_ids: set[str],
) -> dict[str, list[ToolCall]]:
    """Read per-session tool calls out of the ``messages`` table.

    Hermes stores calls in the OpenAI-style shape: an assistant row carries a
    ``tool_calls`` JSON array, and the matching result row carries ``tool_call_id`` and
    ``tool_name``. Results are collected first so a call can be resolved against its own
    result regardless of the order rows are read in.

    Hermes records no per-call error flag, so a call with a result is reported as
    completed and a call whose result never arrived is reported as unknown.
    """
    if not session_ids:
        return {}

    completed: set[str] = set()
    denied: set[str] = set()
    pending: dict[str, list[dict]] = {}

    rows = _fetchall(
        connection,
        "SELECT session_id, tool_calls, tool_call_id, effect_disposition FROM messages",
    )
    for row in rows:
        session_id = row["session_id"]
        if session_id not in session_ids:
            continue
        call_id = row["tool_call_id"]
        if isinstance(call_id, str) and call_id:
            key = f"{session_id}\x00{call_id}"
            disposition = row["effect_disposition"]
            if isinstance(disposition, str) and disposition.lower() in ("denied", "rejected", "blocked"):
                denied.add(key)
            else:
                completed.add(key)
        raw_calls = row["tool_calls"]
        if not isinstance(raw_calls, str) or not raw_calls.strip():
            continue
        try:
            parsed = json.loads(raw_calls)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, list):
            continue
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            function = entry.get("function")
            function = function if isinstance(function, dict) else {}
            entry_id = entry.get("id")
            pending.setdefault(session_id, []).append(
                {
                    "name": function.get("name") or entry.get("name"),
                    "arguments": function.get("arguments"),
                    "call_id": entry_id if isinstance(entry_id, str) else None,
                }
            )

    calls: dict[str, list[ToolCall]] = {}
    for session_id, records in pending.items():
        resolved: list[ToolCall] = []
        for record in records:
            call_id = record.get("call_id")
            status = TOOL_STATUS_UNKNOWN
            if isinstance(call_id, str):
                key = f"{session_id}\x00{call_id}"
                if key in denied:
                    status = TOOL_STATUS_ERROR
                elif key in completed:
                    status = TOOL_STATUS_COMPLETED
            resolved.append(
                make_tool_call(record["name"], record["arguments"], status=status)
            )
        calls[session_id] = resolved
    return calls
