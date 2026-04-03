from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .ingest import iter_session_details
from .metrics import details_for_last_days, parse_since_days
from .models import ImportSummary, SessionDetails, SessionRecord


def export_payload(paths, since: str | None = None) -> dict:
    details = iter_session_details(paths)
    if since:
        details = details_for_last_days(paths, parse_since_days(since))
    return {
        "schema_version": 1,
        "exported_at": datetime.now(tz=UTC).isoformat(),
        "sessions": [detail.to_dict() for detail in details],
    }


def export_payload_from_details(details: list[SessionDetails]) -> dict:
    return {
        "schema_version": 1,
        "exported_at": datetime.now(tz=UTC).isoformat(),
        "sessions": [detail.to_dict() for detail in details],
    }


def write_export(paths, output_path: Path, since: str | None = None) -> Path:
    payload = export_payload(paths, since=since)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def write_merged_export(input_paths: list[Path], output_path: Path) -> tuple[Path, ImportSummary]:
    details, summary = read_imports_with_summary(input_paths)
    payload = export_payload_from_details(details)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output_path, summary


def read_import(input_path: Path) -> list[SessionDetails]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    sessions = payload.get("sessions", [])
    return [_session_detail_from_dict(item) for item in sessions]


def read_imports(input_paths: list[Path]) -> list[SessionDetails]:
    return read_imports_with_summary(input_paths)[0]


def read_imports_with_summary(input_paths: list[Path]) -> tuple[list[SessionDetails], ImportSummary]:
    merged: dict[str, SessionDetails] = {}
    sessions_loaded = 0
    for input_path in input_paths:
        for detail in read_import(input_path):
            sessions_loaded += 1
            session_id = detail.session.session_id
            existing = merged.get(session_id)
            if existing is None or detail.session.updated_at >= existing.session.updated_at:
                merged[session_id] = detail
    ordered = sorted(merged.values(), key=lambda detail: detail.session.updated_at, reverse=True)
    timestamps = [detail.session.updated_at.isoformat() for detail in ordered]
    summary = ImportSummary(
        files_read=len(input_paths),
        sessions_loaded=sessions_loaded,
        duplicates_removed=max(sessions_loaded - len(ordered), 0),
        merged_sessions=len(ordered),
        oldest_session_at=timestamps[-1] if timestamps else None,
        newest_session_at=timestamps[0] if timestamps else None,
    )
    return ordered, summary


def _session_detail_from_dict(payload: dict) -> SessionDetails:
    session_payload = payload["session"]
    session = SessionRecord(
        session_id=session_payload["session_id"],
        created_at=datetime.fromisoformat(session_payload["created_at"]),
        updated_at=datetime.fromisoformat(session_payload["updated_at"]),
        cwd=session_payload["cwd"],
        model=session_payload.get("model"),
        model_provider=session_payload["model_provider"],
        tokens_used=int(session_payload["tokens_used"]),
        rollout_path=Path(session_payload["rollout_path"]),
        git_branch=session_payload.get("git_branch"),
        git_origin_url=session_payload.get("git_origin_url"),
    )
    started_at = payload.get("started_at")
    return SessionDetails(
        session=session,
        request_count=int(payload.get("request_count", 0)),
        input_tokens=_as_optional_int(payload.get("input_tokens")),
        output_tokens=_as_optional_int(payload.get("output_tokens")),
        cached_input_tokens=_as_optional_int(payload.get("cached_input_tokens")),
        reasoning_output_tokens=_as_optional_int(payload.get("reasoning_output_tokens")),
        total_tokens_from_rollout=_as_optional_int(payload.get("total_tokens_from_rollout")),
        started_at=datetime.fromisoformat(started_at) if started_at else None,
    )


def _as_optional_int(value):
    if value is None:
        return None
    return int(value)
