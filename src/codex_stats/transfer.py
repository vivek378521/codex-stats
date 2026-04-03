from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .ingest import iter_session_details
from .models import SessionDetails, SessionRecord


def export_payload(paths) -> dict:
    details = iter_session_details(paths)
    return {
        "schema_version": 1,
        "exported_at": datetime.now(tz=UTC).isoformat(),
        "sessions": [detail.to_dict() for detail in details],
    }


def write_export(paths, output_path: Path) -> Path:
    payload = export_payload(paths)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def read_import(input_path: Path) -> list[SessionDetails]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    sessions = payload.get("sessions", [])
    return [_session_detail_from_dict(item) for item in sessions]


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
