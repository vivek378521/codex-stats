from __future__ import annotations

import json
from datetime import UTC

from .models import BreakdownEntry, SessionDetails, TimeSummary


def format_summary(summary: TimeSummary) -> str:
    lines = [
        "Codex Usage Summary",
        "",
        f"Window: {summary.label}",
        f"Sessions: {summary.sessions}",
        f"Requests: {summary.requests}",
        f"Input tokens: {summary.input_tokens:,}",
        f"Output tokens: {summary.output_tokens:,}",
        f"Cached input tokens: {summary.cached_input_tokens:,}",
        f"Reasoning tokens: {summary.reasoning_output_tokens:,}",
        f"Total tokens: {summary.total_tokens:,}",
        f"Estimated cost: ${summary.estimated_cost_usd:.2f}",
    ]
    if summary.top_model:
        lines.append(f"Top model: {summary.top_model}")
    return "\n".join(lines)


def format_session(details: SessionDetails) -> str:
    session = details.session
    lines = [
        "Session Summary",
        "",
        f"Session ID: {session.session_id}",
        f"Project: {session.project_name}",
        f"Model: {session.model or 'unknown'}",
        f"Started: {_fmt_dt(details.started_at or session.created_at)}",
        f"Updated: {_fmt_dt(session.updated_at)}",
        f"Requests: {details.request_count}",
        f"Input tokens: {_fmt_optional_int(details.input_tokens)}",
        f"Output tokens: {_fmt_optional_int(details.output_tokens)}",
        f"Cached input tokens: {_fmt_optional_int(details.cached_input_tokens)}",
        f"Reasoning tokens: {_fmt_optional_int(details.reasoning_output_tokens)}",
        f"Total tokens: {details.effective_total_tokens():,}",
    ]
    return "\n".join(lines)


def as_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def format_breakdown(title: str, entries: list[BreakdownEntry]) -> str:
    lines = [title, ""]
    if not entries:
        lines.append("No data.")
        return "\n".join(lines)
    for entry in entries:
        lines.append(f"{entry.name}")
        lines.append(f"  Sessions: {entry.sessions}")
        lines.append(f"  Requests: {entry.requests}")
        lines.append(f"  Total tokens: {entry.total_tokens:,}")
        lines.append(f"  Estimated cost: ${entry.estimated_cost_usd:.2f}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _fmt_dt(value) -> str:
    return value.astimezone(UTC).isoformat() if value else "unknown"


def _fmt_optional_int(value: int | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:,}"
