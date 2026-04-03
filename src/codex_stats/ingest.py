from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path

from .config import Paths
from .models import SessionDetails, SessionRecord


def _dt_from_unix(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=UTC)


def _connect_sqlite(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def iter_sessions(paths: Paths) -> Iterable[SessionRecord]:
    if not paths.state_db.exists():
        return []

    query = """
        SELECT
            id,
            created_at,
            updated_at,
            cwd,
            model,
            model_provider,
            tokens_used,
            rollout_path,
            git_branch,
            git_origin_url
        FROM threads
        ORDER BY updated_at DESC, created_at DESC
    """
    with _connect_sqlite(paths.state_db) as connection:
        rows = connection.execute(query).fetchall()

    sessions: list[SessionRecord] = []
    for row in rows:
        sessions.append(
            SessionRecord(
                session_id=row["id"],
                created_at=_dt_from_unix(row["created_at"]),
                updated_at=_dt_from_unix(row["updated_at"]),
                cwd=row["cwd"],
                model=row["model"],
                model_provider=row["model_provider"],
                tokens_used=row["tokens_used"],
                rollout_path=Path(row["rollout_path"]),
                git_branch=row["git_branch"],
                git_origin_url=row["git_origin_url"],
            )
        )
    return sessions


def get_session(paths: Paths, session_id: str | None = None) -> SessionRecord | None:
    sessions = list(iter_sessions(paths))
    if not sessions:
        return None
    if session_id is None:
        return sessions[0]
    for session in sessions:
        if session.session_id == session_id:
            return session
    return None


def iter_session_details(paths: Paths) -> list[SessionDetails]:
    return [get_session_details(paths, session) for session in iter_sessions(paths)]


def _read_rollout_details(path: Path) -> dict[str, int | str | None]:
    details: dict[str, int | str | None] = {
        "request_count": 0,
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": None,
        "reasoning_output_tokens": None,
        "total_tokens_from_rollout": None,
        "started_at": None,
    }
    if not path.exists():
        return details

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            payload = event.get("payload", {})
            if event_type == "session_meta":
                timestamp = payload.get("timestamp")
                if isinstance(timestamp, str):
                    details["started_at"] = timestamp
            if event_type != "event_msg":
                continue

            payload_type = payload.get("type")
            if payload_type == "user_message":
                details["request_count"] = int(details["request_count"] or 0) + 1
            elif payload_type == "token_count":
                info = payload.get("info") or {}
                total_usage = info.get("total_token_usage") or {}
                if total_usage:
                    details["input_tokens"] = total_usage.get("input_tokens")
                    details["output_tokens"] = total_usage.get("output_tokens")
                    details["cached_input_tokens"] = total_usage.get("cached_input_tokens")
                    details["reasoning_output_tokens"] = total_usage.get("reasoning_output_tokens")
                    details["total_tokens_from_rollout"] = total_usage.get("total_tokens")

    return details


def get_session_details(paths: Paths, session: SessionRecord) -> SessionDetails:
    rollout_details = _read_rollout_details(session.rollout_path)
    started_at_raw = rollout_details["started_at"]
    started_at = None
    if isinstance(started_at_raw, str):
        started_at = datetime.fromisoformat(started_at_raw.replace("Z", "+00:00"))

    return SessionDetails(
        session=session,
        request_count=int(rollout_details["request_count"] or 0),
        input_tokens=_as_optional_int(rollout_details["input_tokens"]),
        output_tokens=_as_optional_int(rollout_details["output_tokens"]),
        cached_input_tokens=_as_optional_int(rollout_details["cached_input_tokens"]),
        reasoning_output_tokens=_as_optional_int(rollout_details["reasoning_output_tokens"]),
        total_tokens_from_rollout=_as_optional_int(rollout_details["total_tokens_from_rollout"]),
        started_at=started_at,
    )


def sessions_for_day(paths: Paths, target_day: date, timezone: tzinfo | None = None) -> list[SessionRecord]:
    return [
        session
        for session in iter_sessions(paths)
        if session.created_at.astimezone(timezone or UTC).date() == target_day
    ]


def _as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(value)
