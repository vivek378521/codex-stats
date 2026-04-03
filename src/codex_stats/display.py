from __future__ import annotations

import json
import os
import textwrap
from datetime import UTC
from dataclasses import dataclass

from .models import (
    BreakdownEntry,
    CompareReport,
    CostSummary,
    DailyPoint,
    DoctorCheck,
    HistoryEntry,
    InsightReport,
    SessionDetails,
    TimeSummary,
)


@dataclass(frozen=True)
class FormatOptions:
    color: bool = False


def resolve_format_options(color_mode: str = "auto") -> FormatOptions:
    if color_mode == "always":
        return FormatOptions(color=True)
    if color_mode == "never":
        return FormatOptions(color=False)
    no_color = os.environ.get("NO_COLOR")
    return FormatOptions(color=not bool(no_color) and os.isatty(1))


def format_summary(summary: TimeSummary, options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    cache_ratio = _fmt_percent(summary.cache_ratio)
    usage_bar = _bar(summary.cache_ratio or 0.0, options)
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
    return _card("Codex Usage", rows, options)


def format_session(details: SessionDetails, options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
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
    return _card("Session Summary", rows, options)


def as_json(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def format_breakdown(title: str, entries: list[BreakdownEntry], options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    if not entries:
        return _card(title, [("Status", "No data")], options)
    lines = [_box_top(title, options)]
    for index, entry in enumerate(entries):
        share = entry.total_tokens / entries[0].total_tokens if entries[0].total_tokens else 0.0
        lines.append(_box_line(_accent(entry.name, options)))
        lines.append(_box_line(f"  Sessions: {entry.sessions}"))
        lines.append(_box_line(f"  Requests: {entry.requests}"))
        lines.append(_box_line(f"  Tokens:   {entry.total_tokens:,}"))
        lines.append(_box_line(f"  Cost:     ${entry.estimated_cost_usd:.2f}"))
        lines.append(_box_line(f"  Share:    {_bar(share, options)}"))
        if index != len(entries) - 1:
            lines.append(_box_separator())
    lines.append(_box_bottom())
    return "\n".join(lines)


def format_history(entries: list[HistoryEntry], options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    if not entries:
        return _card("Recent Sessions", [("Status", "No data")], options)
    lines = [_box_top("Recent Sessions", options)]
    for entry in entries:
        model = entry.model or "unknown"
        lines.append(_box_line(f"{_fmt_short_dt(entry.updated_at)}  {_accent(entry.project_name, options)}  {model}"))
        lines.append(_box_line(f"  requests={entry.requests:<4} tokens={entry.total_tokens:,} cost=${entry.estimated_cost_usd:.2f}"))
    lines.append(_box_bottom())
    return "\n".join(lines)


def format_costs(costs: CostSummary, options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    rows = [
        ("Today", f"${costs.today_cost_usd:.2f}"),
        ("Week", f"${costs.week_cost_usd:.2f}"),
        ("Month", f"${costs.month_cost_usd:.2f}"),
        ("Projected month", f"${costs.projected_monthly_cost_usd:.2f}"),
        ("Highest session", f"${costs.highest_session_cost_usd:.2f}"),
    ]
    return _card("Cost Breakdown", rows, options)


def format_insights(insights: InsightReport, options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    rows = [
        ("Avg/request", f"{insights.average_tokens_per_request:,.0f}"),
        ("Cache ratio", _fmt_percent(insights.cache_ratio)),
        ("Large sessions", str(insights.large_session_count)),
        ("Largest session", f"{insights.largest_session_tokens:,}"),
        ("Possible savings", f"${insights.possible_savings_usd:.2f}"),
        ("Suggestion", insights.suggestion),
    ]
    return _card("Insights", rows, options)


def format_daily(points: list[DailyPoint], options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    if not points:
        return _card("Daily Usage", [("Status", "No data")], options)
    max_tokens = max((point.total_tokens for point in points), default=0)
    sparkline = _sparkline([point.total_tokens for point in points], options)
    lines = [_box_top("Daily Usage", options)]
    lines.append(_box_line(f"Trend   {sparkline}"))
    lines.append(_box_separator())
    for point in points:
        ratio = point.total_tokens / max_tokens if max_tokens else 0.0
        bar = _bar(ratio, options, width=10)
        label = point.day[5:]
        lines.append(_box_line(f"{label}  {bar}  {point.total_tokens:>10,}  {point.requests:>3} req"))
    lines.append(_box_bottom())
    return "\n".join(lines)


def format_compare(report: CompareReport, options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    pct = "n/a" if report.total_tokens_delta_pct is None else f"{report.total_tokens_delta_pct:+.1f}%"
    rows = [
        ("Current", f"{report.current.total_tokens:,} tokens"),
        ("Previous", f"{report.previous.total_tokens:,} tokens"),
        ("Delta", f"{report.total_tokens_delta:+,}"),
        ("Delta %", pct),
        ("Request delta", f"{report.requests_delta:+d}"),
        ("Cost delta", f"${report.cost_delta_usd:+.2f}"),
    ]
    return _card("Compare", rows, options)


def format_doctor(checks: list[DoctorCheck], options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    lines = [_box_top("Doctor", options)]
    for check in checks:
        status = _tint("OK", "32", options) if check.ok else _tint("WARN", "31", options)
        lines.append(_box_line(f"{status:<4} {check.name:<14} {check.detail}"))
    lines.append(_box_bottom())
    return "\n".join(lines)


def _card(title: str, rows: list[tuple[str, str]], options: FormatOptions) -> str:
    inner_width = 51
    lines = [_box_top(title, options)]
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


def _box_top(title: str, options: FormatOptions) -> str:
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


def _bar(value: float, options: FormatOptions, width: int = 16) -> str:
    safe_value = min(max(value, 0.0), 1.0)
    filled = round(safe_value * width)
    bar = "█" * filled + "░" * (width - filled)
    return _tint(bar, "36", options) if options.color else bar


def _sparkline(values: list[int], options: FormatOptions) -> str:
    if not values:
        return ""
    ticks = "▁▂▃▄▅▆▇█"
    max_value = max(values)
    if max_value <= 0:
        line = ticks[0] * len(values)
    else:
        line = "".join(ticks[min(len(ticks) - 1, round((value / max_value) * (len(ticks) - 1)))] for value in values)
    return _tint(line, "35", options) if options.color else line


def _accent(text: str, options: FormatOptions) -> str:
    return _tint(text, "33", options)


def _tint(text: str, code: str, options: FormatOptions) -> str:
    if not options.color:
        return text
    return f"\033[{code}m{text}\033[0m"
