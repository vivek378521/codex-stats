from __future__ import annotations

import difflib
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .config import Paths
from .models import FileEdit, SessionDetails, SessionRecord


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
    connection = _connect_sqlite(paths.state_db)
    try:
        rows = connection.execute(query).fetchall()
    finally:
        connection.close()

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
                source="codex",
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


def _read_rollout(path: Path) -> tuple[dict[str, int | str | None], list[FileEdit]]:
    details: dict[str, int | str | None] = {
        "request_count": 0,
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": None,
        "reasoning_output_tokens": None,
        "total_tokens_from_rollout": None,
        "started_at": None,
    }
    edits: list[FileEdit] = []
    if not path.exists():
        return details, edits

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
            if not isinstance(payload, dict):
                payload = {}
            if event_type == "session_meta":
                timestamp = payload.get("timestamp")
                if isinstance(timestamp, str):
                    details["started_at"] = timestamp

            payload_type = payload.get("type")
            edits.extend(_edits_from_event(payload_type, payload))

            if event_type != "event_msg":
                continue

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

    return details, edits


def is_file_editing_tool(name: object) -> bool:
    if not isinstance(name, str) or not name:
        return False
    lowered = name.lower()
    exact_tools = {
        "update_file",
        "create_file",
        "copy_file",
        "move_file",
        "delete_file",
        "edit",
        "open_edit",
        "multiedit",
        "multi_edit",
        "multi-edit",
        "notebookedit",
        "write",
        "write_file",
        "write_to_file",
        "apply_patch",
        "applypatch",
        "insert",
        "replace",
    }
    if lowered in exact_tools or lowered.startswith("mcp__") and lowered[5:] in exact_tools:
        return True
    return (
        "patch" in lowered
        or ("edit" in lowered and "read" not in lowered)
        or ("write" in lowered and "file" in lowered)
        or ("create" in lowered and "file" in lowered)
        or ("update" in lowered and "file" in lowered)
        or ("delete" in lowered and "file" in lowered)
    )


def count_line_changes(old_text: str, new_text: str) -> tuple[int, int]:
    matcher = difflib.SequenceMatcher(
        None,
        old_text.splitlines(),
        new_text.splitlines(),
        autojunk=False,
    )
    insertions = 0
    deletions = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("insert", "replace"):
            insertions += j2 - j1
        if tag in ("delete", "replace"):
            deletions += i2 - i1
    return insertions, deletions


def patch_line_stats(text: str) -> tuple[int, int]:
    insertions = 0
    deletions = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("+++") or line.startswith("---") or line.startswith("***"):
            continue
        if line.startswith("+"):
            insertions += 1
        elif line.startswith("-"):
            deletions += 1
    return insertions, deletions


_PATCH_FILE_MARKERS = (
    "*** Add File:",
    "*** Update File:",
    "*** Delete File:",
    "*** Update and Move File:",
)


def file_edits_from_patch(name: object, patch_text: str) -> list[FileEdit]:
    if not is_file_editing_tool(name):
        return []
    sections: list[tuple[str, str, str]] = []
    current_path: str | None = None
    current_action = "updated"
    current_lines: list[str] = []
    for raw_line in patch_text.splitlines():
        line = raw_line.strip()
        marker = next((prefix for prefix in _PATCH_FILE_MARKERS if line.startswith(prefix)), None)
        if marker is None:
            current_lines.append(raw_line)
            continue
        if current_path and current_lines:
            sections.append((current_path, current_action, "\n".join(current_lines)))
        current_path = line[len(marker) :].strip()
        current_action = "created" if marker == "*** Add File:" else "deleted" if marker == "*** Delete File:" else "updated"
        current_lines = []
    if current_path and current_lines:
        sections.append((current_path, current_action, "\n".join(current_lines)))

    edits: list[FileEdit] = []
    for path, action, body in sections:
        if not path:
            continue
        insertions, deletions = patch_line_stats(body)
        edits.append(FileEdit(path=path, action=action, insertions=insertions, deletions=deletions))
    return edits


def _patch_path(text: str) -> str | None:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("*** Update File:") or line.startswith("*** Delete File:"):
            candidate = line.split(":", 1)[1].strip()
            if candidate:
                return candidate
        if line.startswith("+++ b/"):
            candidate = line[len("+++ b/") :].strip()
            if candidate and candidate != "/dev/null":
                return candidate
        if line.startswith("--- a/"):
            candidate = line[len("--- a/") :].strip()
            if candidate and candidate != "/dev/null":
                return candidate
    return None


def _edit_path_from_args(args: dict) -> str | None:
    for key in ("file_path", "filepath", "path", "file"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def file_edit_from_args(name: object, args: object) -> FileEdit | None:
    if not is_file_editing_tool(name):
        return None
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(args, dict):
        return None

    patch_value = args.get("patch")
    patch_text = patch_value if isinstance(patch_value, str) and patch_value.strip() else None
    path = _edit_path_from_args(args)
    if path is None and patch_text:
        path = _patch_path(patch_text)
    if path is None:
        return None

    lowered = str(name).lower()
    old_text = str(args.get("old_string") or "")
    new_text = str(args.get("new_string") or "")
    content_value = args.get("content") or args.get("file_content")
    content = str(content_value) if isinstance(content_value, str) and content_value.strip() else ""
    patch_marker = patch_text or ""
    if "delete" in lowered or "*** Delete File:" in patch_marker:
        action = "deleted"
    elif "create" in lowered or "*** Add File:" in patch_marker or lowered in ("write", "write_to_file", "write_file"):
        action = "created" if not old_text else "updated"
    elif not new_text and old_text and patch_text is None:
        action = "deleted"
    else:
        action = "updated"

    if patch_text:
        insertions, deletions = patch_line_stats(patch_text)
    elif content:
        insertions, deletions = len(content.splitlines()) or 1, 0
    elif old_text or new_text:
        insertions, deletions = count_line_changes(old_text, new_text)
        if action == "created":
            insertions = max(insertions, len(new_text.splitlines()) or 1)
        elif action == "deleted":
            deletions = max(deletions, len(old_text.splitlines()) or 1)
    else:
        insertions, deletions = 1, 0

    if insertions == 0 and deletions == 0:
        insertions = 1
    return FileEdit(path=path, action=action, insertions=insertions, deletions=deletions)


def _parse_tool_call_arguments(arguments: object) -> dict | None:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _find_tool_call(payload: dict) -> dict | None:
    for key in ("tool_call", "agent_message", "agent_code", "message", "agent_action"):
        container = payload.get(key)
        if isinstance(container, dict):
            tool_call = container.get("tool_call")
            if isinstance(tool_call, dict):
                return tool_call
    return None


def _tool_call_arguments(name: object, raw_input: object) -> object:
    if isinstance(raw_input, dict):
        return raw_input
    if not isinstance(raw_input, str) or not raw_input.strip():
        return None
    text = raw_input.strip()
    args = _parse_tool_call_arguments(text)
    if args is not None:
        return args
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return _parse_tool_call_arguments(text[start : end + 1])
    return None


def _edits_from_event(payload_type: object, payload: dict) -> list[FileEdit]:
    if payload_type == "custom_tool_call":
        name = payload.get("name")
        raw_input = payload.get("input")
        if isinstance(raw_input, str) and raw_input.strip():
            if "*** Begin Patch" in raw_input or raw_input.lstrip().startswith(("+++", "---")):
                return file_edits_from_patch(name, raw_input)
            args = _tool_call_arguments(name, raw_input)
            args_with_patch = None
            if isinstance(args, dict) and isinstance(args.get("patch"), str) and "*** Begin Patch" in args["patch"]:
                args_with_patch = args["patch"]
            if args_with_patch:
                return file_edits_from_patch(name, args_with_patch)
        edit = file_edit_from_args(name, _tool_call_arguments(name, raw_input))
        return [edit] if edit is not None else []
    edit = _edit_from_event_payload(payload_type, payload)
    return [edit] if edit is not None else []


def _edit_from_event_payload(payload_type: object, payload: dict) -> FileEdit | None:
    if payload_type == "custom_tool_call":
        name = payload.get("name")
        raw_input = payload.get("input")
        if isinstance(raw_input, str) and ("*** Begin Patch" in raw_input or raw_input.lstrip().startswith(("+++", "---"))):
            return None
        args = _tool_call_arguments(name, raw_input)
        return file_edit_from_args(name, args)

    tool_call = _find_tool_call(payload)
    if tool_call is not None:
        edit = file_edit_from_args(tool_call.get("name"), tool_call.get("arguments"))
        if edit is not None:
            return edit

    if isinstance(payload_type, str) and is_file_editing_tool(payload_type):
        nested = payload.get(payload_type)
        if nested is None:
            nested = payload.get("arguments")
        return file_edit_from_args(payload_type, nested)
    return None


def get_session_details(paths: Paths, session: SessionRecord) -> SessionDetails:
    rollout_details, edits = _read_rollout(session.rollout_path)
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
        file_edits=tuple(edits),
    )


def _as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(value)
