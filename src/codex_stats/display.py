from __future__ import annotations

import json
import textwrap
from datetime import UTC

from .models import BreakdownEntry, CostSummary, HistoryEntry, InsightReport, SessionDetails, TimeSummary


def format_summary(summary: TimeSummary) -> str:
    cache_ratio = _fmt_percent(summary.cache_ratio)
    usage_bar = _bar(summary.cache_ratio or 0.0)
    rows = [
        ("Window", summary.label),
        ("Sessions", str(summary.sessions)),
        ("Requests", str(summary.requests)),
        ("Top model", summary.top_model or "unknown"),
        ("Total tokens", f"{summary.total_tokens:,}"),
        ("Estimated cost", f"${summary.estimated_cost_usd:.2f}"),
        ("Avg/request", f"{summary.average_tokens_per_request:,.0f}"),
        ("Cache ratio", cache_ratio),
        ("Usage", usage_bar),
    ]
    return _card("Codex Usage", rows)


def format_session(details: SessionDetails) -> str:
    session = details.session
    rows = [
        ("Session ID", session.session_id),
        ("Project", session.project_name),
        ("Model", session.model or "unknown"),
        ("Started", _fmt_dt(details.started_at or session.created_at)),
        ("Updated", _fmt_dt(session.updated_at)),
        ("Requests", str(details.request_count)),
        ("Input", _fmt_optional_int(details.input_tokens)),
        ("Output", _fmt_optional_int(details.output_tokens)),
        ("Cached input", _fmt_optional_int(details.cached_input_tokens)),
        ("Reasoning", _fmt_optional_int(details.reasoning_output_tokens)),
        ("Total tokens", f"{details.effective_total_tokens():,}"),
        ("Estimated cost", f"${details.effective_total_tokens() / 1000 * 0.01:.2f}"),
    ]
    return _card("Session Summary", rows)


def as_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def format_breakdown(title: str, entries: list[BreakdownEntry]) -> str:
    if not entries:
        return _card(title, [("Status", "No data")])
    lines = [_box_top(title)]
    for index, entry in enumerate(entries):
        share = entry.total_tokens / entries[0].total_tokens if entries[0].total_tokens else 0.0
        lines.append(_box_line(entry.name))
        lines.append(_box_line(f"  Sessions: {entry.sessions}"))
        lines.append(_box_line(f"  Requests: {entry.requests}"))
        lines.append(_box_line(f"  Tokens:   {entry.total_tokens:,}"))
        lines.append(_box_line(f"  Cost:     ${entry.estimated_cost_usd:.2f}"))
        lines.append(_box_line(f"  Share:    {_bar(share)}"))
        if index != len(entries) - 1:
            lines.append(_box_separator())
    lines.append(_box_bottom())
    return "\n".join(lines)


def format_history(entries: list[HistoryEntry]) -> str:
    if not entries:
        return _card("Recent Sessions", [("Status", "No data")])
    lines = [_box_top("Recent Sessions")]
    for entry in entries:
        model = entry.model or "unknown"
        lines.append(_box_line(f"{_fmt_short_dt(entry.updated_at)}  {entry.project_name}  {model}"))
        lines.append(_box_line(f"  requests={entry.requests:<4} tokens={entry.total_tokens:,} cost=${entry.estimated_cost_usd:.2f}"))
    lines.append(_box_bottom())
    return "\n".join(lines)


def format_costs(costs: CostSummary) -> str:
    rows = [
        ("Today", f"${costs.today_cost_usd:.2f}"),
        ("Week", f"${costs.week_cost_usd:.2f}"),
        ("Month", f"${costs.month_cost_usd:.2f}"),
        ("Projected month", f"${costs.projected_monthly_cost_usd:.2f}"),
        ("Highest session", f"${costs.highest_session_cost_usd:.2f}"),
    ]
    return _card("Cost Breakdown", rows)


def format_insights(insights: InsightReport) -> str:
    rows = [
        ("Avg/request", f"{insights.average_tokens_per_request:,.0f}"),
        ("Cache ratio", _fmt_percent(insights.cache_ratio)),
        ("Large sessions", str(insights.large_session_count)),
        ("Largest session", f"{insights.largest_session_tokens:,}"),
        ("Possible savings", f"${insights.possible_savings_usd:.2f}"),
        ("Suggestion", insights.suggestion),
    ]
    return _card("Insights", rows)


def _card(title: str, rows: list[tuple[str, str]]) -> str:
    inner_width = 51
    lines = [_box_top(title)]
    key_width = max(len(key) for key, _ in rows)
    for key, value in rows:
        prefix = f"{key:<{key_width}}  "
        wrapped = textwrap.wrap(value, width=max(inner_width - len(prefix), 12)) or [""]
        for index, chunk in enumerate(wrapped):
            if index == 0:
                lines.append(_box_line(f"{prefix}{chunk}"))
            else:
                lines.append(_box_line(f"{' ' * len(prefix)}{chunk}"))
    lines.append(_box_bottom())
    return "\n".join(lines)


def _box_top(title: str) -> str:
    width = 53
    title_text = f" {title} "
    fill = max(width - len(title_text) - 2, 0)
    return "+" + "-" * (fill // 2) + title_text + "-" * (fill - fill // 2) + "+"


def _box_separator() -> str:
    return "|" + "-" * 53 + "|"


def _box_bottom() -> str:
    return "+" + "-" * 53 + "+"


def _box_line(text: str) -> str:
    return f"| {text:<51}|"


def _fmt_dt(value) -> str:
    return value.astimezone(UTC).isoformat() if value else "unknown"


def _fmt_short_dt(value) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _fmt_optional_int(value: int | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:,}"


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value * 100:.1f}%"


def _bar(value: float, width: int = 16) -> str:
    safe_value = min(max(value, 0.0), 1.0)
    filled = round(safe_value * width)
    return "█" * filled + "░" * (width - filled)
