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
from .ingest import iter_session_details as _codex_iter_session_details
from .models import SessionDetails, SessionRecord

SOURCE_CODEX = "codex"
SOURCE_OPENCODE = "opencode"
SOURCE_CLAUDE = "claude"
SOURCE_HERMES = "hermes"

CLAUDE_PROVIDER = "anthropic"
HERMES_PROVIDER = "hermes"
OPENCODE_PROVIDER = "opencode"


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    description: str
    available: bool
    path_hint: str
    ingest: Callable[[], list[SessionDetails]] = field(repr=False, compare=False)


def _codex_source(paths: Paths | None = None) -> Source:
    paths = paths or Paths.discover()
    return Source(
        key=SOURCE_CODEX,
        label="Codex",
        description="OpenAI Codex CLI sessions from the local ~/.codex state database and rollout files.",
        available=paths.state_db.exists(),
        path_hint=str(paths.codex_home),
        ingest=lambda: _codex_iter_session_details(paths),
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
        description="Local opencode sessions from the opencode.sqlite database, which records cost and token usage directly.",
        available=db_path.exists(),
        path_hint=str(root),
        ingest=lambda: _ingest_opencode(db_path),
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


def iter_sources(paths: Paths | None = None) -> list[Source]:
    return [factory(paths) for factory in _SOURCE_FACTORIES]


def source_label(source_key: str) -> str:
    return SOURCE_LABELS.get(source_key, source_key.capitalize())


def iter_all_details() -> list[SessionDetails]:
    all_details: list[SessionDetails] = []
    for source in iter_sources():
        try:
            all_details.extend(source.ingest() or [])
        except Exception:
            continue
    return all_details


def _dt_from_unix_seconds(value: float | int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)


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


def _ingest_opencode(db_path: Path) -> list[SessionDetails]:
    if not db_path.exists():
        return []
    connection = _connect_sqlite(db_path)
    details: list[SessionDetails] = []
    try:
        rows = connection.execute(
            """
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
                time_updated
            FROM session
            WHERE time_updated > 0
            ORDER BY time_updated DESC
            """
        ).fetchall()
        request_counts = {
            row["session_id"]: row["count"]
            for row in connection.execute(
                """
                SELECT session_id, COUNT(*) AS count
                FROM message
                WHERE json_extract(data, '$.role') = 'user'
                GROUP BY session_id
                """
            ).fetchall()
        } if rows else {}
    finally:
        connection.close()

    for row in rows:
        created_at = _dt_from_unix_seconds(row["time_created"] / 1000)
        updated_at = _dt_from_unix_seconds(row["time_updated"] / 1000)
        if created_at is None or updated_at is None:
            continue
        input_tokens = _as_int(row["tokens_input"])
        output_tokens = _as_int(row["tokens_output"])
        reasoning_tokens = _as_int(row["tokens_reasoning"])
        cached_input_tokens = _as_int(row["tokens_cache_read"]) + _as_int(row["tokens_cache_write"])
        total_tokens = input_tokens + output_tokens + reasoning_tokens + cached_input_tokens
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
                cached_input_tokens=cached_input_tokens,
                reasoning_output_tokens=reasoning_tokens,
                total_tokens_from_rollout=total_tokens,
                started_at=created_at,
                recorded_cost_usd=_as_float(row["cost"]),
            )
        )
    return details


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
    grouped: dict[str, SessionDetails] = {}
    for project_dir in sorted(path for path in projects_dir.iterdir() if path.is_dir()):
        for path in sorted(project_dir.glob("*.jsonl")):
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


def _parse_claude_session(path: Path) -> SessionDetails | None:
    timestamps: list[str] = []
    user_count = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    model_counter: Counter[str] = Counter()
    cwd: str | None = None
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
            event_type = event.get("type")
            if event_type == "user":
                user_count += 1
            if event_type != "assistant":
                continue
            message = event.get("message")
            if not isinstance(message, dict):
                continue
            if isinstance(message.get("model"), str):
                model_counter[message["model"]] += 1
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            input_tokens += _as_int(usage.get("input_tokens"))
            output_tokens += _as_int(usage.get("output_tokens"))
            cache_read_tokens += _as_int(usage.get("cache_read_input_tokens"))
            cache_write_tokens += _as_int(usage.get("cache_creation_input_tokens"))

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
        git_branch=None,
        git_origin_url=None,
        source=SOURCE_CLAUDE,
    )
    return SessionDetails(
        session=session,
        request_count=user_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cache_read_tokens,
        reasoning_output_tokens=None,
        total_tokens_from_rollout=total_tokens,
        started_at=created_at,
    )


def _decode_claude_project_path(encoded: str) -> str:
    decoded = encoded.replace("-", "/")
    return decoded if decoded.startswith("/") else f"/{decoded}"


def _ingest_hermes(state_db: Path) -> list[SessionDetails]:
    if not state_db.exists():
        return []
    connection = _connect_sqlite(state_db)
    details: list[SessionDetails] = []
    try:
        rows = connection.execute(
            """
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
                title
            FROM sessions
            WHERE started_at > 0
            ORDER BY started_at DESC
            """
        ).fetchall()
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
                cached_input_tokens=cache_read_tokens + cache_write_tokens,
                reasoning_output_tokens=reasoning_tokens,
                total_tokens_from_rollout=total_tokens,
                started_at=created_at,
                recorded_cost_usd=_as_float(row["estimated_cost_usd"]),
            )
        )
    return details