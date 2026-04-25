from __future__ import annotations

import json
import os
import textwrap
from datetime import UTC, datetime
from dataclasses import dataclass
from html import escape

from .config import PricingConfig
from .metrics import estimate_detail_cost
from .models import (
    BreakdownEntry,
    CompareReport,
    ConfigView,
    CostSummary,
    DashboardData,
    DashboardWindow,
    DailyPoint,
    DoctorCheck,
    HeatmapCell,
    HistoryEntry,
    InsightReport,
    ImportSummary,
    ProjectDrilldown,
    SessionDetails,
    TimeSummary,
    TopEntry,
    ReportData,
    WatchAlert,
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
        ("Tokens/min", f"{summary.tokens_per_minute:,.0f}"),
        ("Avg session", _fmt_minutes(summary.average_session_duration_minutes)),
        ("Median session", _fmt_minutes(summary.median_session_duration_minutes)),
        ("Cache ratio", cache_ratio),
        ("Usage", usage_bar),
    ]
    return _card("Codex Usage", rows, options)


def format_session(
    details: SessionDetails,
    options: FormatOptions | None = None,
    pricing: PricingConfig | None = None,
) -> str:
    options = options or FormatOptions()
    pricing = pricing or PricingConfig()
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
        ("Estimated cost", f"${estimate_detail_cost(details, pricing):.2f}"),
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
    lines = [_card("Insights", rows, options)]
    if insights.anomalies:
        lines.append("")
        lines.append(_card("Anomalies", [("Detected", "; ".join(insights.anomalies))], options))
    if insights.recommendations:
        lines.append("")
        lines.append(_card("Next Steps", [("Do next", "; ".join(insights.recommendations))], options))
    return "\n".join(lines)


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
        if check.ok:
            status = _tint("OK", "32", options)
        elif check.severity == "warning":
            status = _tint("WARN", "33", options)
        else:
            status = _tint("FAIL", "31", options)
        lines.append(_box_line(f"{status:<4} {check.name:<14} {check.detail}"))
    lines.append(_box_bottom())
    return "\n".join(lines)


def format_top(entries: list[TopEntry], options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    if not entries:
        return _card("Top Sessions", [("Status", "No data")], options)
    lines = [_box_top("Top Sessions", options)]
    for index, entry in enumerate(entries, start=1):
        lines.append(_box_line(f"{index}. {_accent(entry.project_name, options)}  {entry.model or 'unknown'}"))
        lines.append(_box_line(f"   tokens={entry.total_tokens:,} requests={entry.requests} cost=${entry.estimated_cost_usd:.2f}"))
    lines.append(_box_bottom())
    return "\n".join(lines)


def format_config(config: ConfigView, options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    rows = [
        ("Config path", config.config_path),
        ("Exists", "yes" if config.exists else "no"),
        ("Default price", f"${config.pricing_default_usd_per_1k_tokens:.4f}/1k"),
        ("Model overrides", str(len(config.pricing_model_overrides))),
        ("Color", config.display.color),
        ("History limit", str(config.display.history_limit)),
        ("Compare days", str(config.display.compare_days)),
    ]
    lines = [_card("Config", rows, options)]
    if config.pricing_model_overrides:
        override_rows = [(model, f"${rate:.4f}/1k") for model, rate in sorted(config.pricing_model_overrides.items())]
        lines.extend(["", _card("Pricing Overrides", override_rows, options)])
    return "\n".join(lines)


def format_import_summary(summary: ImportSummary, options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    rows = [
        ("Files read", str(summary.files_read)),
        ("Sessions loaded", str(summary.sessions_loaded)),
        ("Duplicates removed", str(summary.duplicates_removed)),
        ("Merged sessions", str(summary.merged_sessions)),
        ("Newest session", summary.newest_session_at or "unknown"),
        ("Oldest session", summary.oldest_session_at or "unknown"),
    ]
    return _card("Import Summary", rows, options)


def format_report(report: ReportData, options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    project_title = report.period.title() if report.project_name is None else f"{report.period.title()} Report: {report.project_name}"
    lines = [
        _card("Report", [("Window", project_title)], options),
        "",
        format_summary(report.summary, options),
        "",
        format_compare(report.comparison, options),
        "",
        format_top(report.top_sessions, options),
        "",
        format_costs(report.costs, options),
        "",
        format_insights(report.insights, options),
    ]
    if report.project_name is None:
        lines[4:4] = ["", format_breakdown("Top Projects", report.projects, options)]
    return "\n".join(lines)


def format_dashboard_html(dashboard: DashboardData) -> str:
    generated_at = dashboard.generated_at.strftime("%Y-%m-%d %H:%M %Z")
    tab_label_overrides = {
        "day": "Today",
        "week": "Last 7 Days",
        "month": "Last 30 Days",
        "all": "All Time",
    }
    tab_buttons = "".join(
        f'<button class="tab-button{" is-active" if index == 0 else ""}" type="button" data-window="{escape(window.key)}">{escape(tab_label_overrides.get(window.key, window.label))}</button>'
        for index, window in enumerate(dashboard.windows)
    )
    window_sections = "".join(
        _format_dashboard_window_section(window, is_active=index == 0)
        for index, window in enumerate(dashboard.windows)
    )
    assets_json = json.dumps(
        {
            window.key: format_dashboard_svg_assets(window)
            for window in dashboard.windows
        },
        separators=(",", ":"),
    )
    summaries_json = json.dumps(
        {
            window.key: _format_window_copy_summary(window)
            for window in dashboard.windows
        },
        separators=(",", ":"),
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Stats Dashboard</title>
  <style>
    :root {{
      --bg: #f6efe3;
      --bg-deep: #efe1cb;
      --panel: rgba(255, 252, 246, 0.94);
      --panel-strong: #fffaf2;
      --ink: #1f1a17;
      --muted: #6c6258;
      --line: rgba(72, 53, 36, 0.14);
      --accent: #0f766e;
      --accent-2: #b45309;
      --good: #166534;
      --warn: #b45309;
      --shadow: 0 18px 56px rgba(75, 56, 40, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(180, 83, 9, 0.16), transparent 26%),
        linear-gradient(180deg, #fbf6ee 0%, var(--bg) 52%, var(--bg-deep) 100%);
      min-height: 100vh;
    }}
    .page {{
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 56px;
    }}
    .hero {{
      padding: 28px;
      border-radius: 28px;
      background: linear-gradient(135deg, rgba(255,255,255,0.88), rgba(255,247,236,0.94));
      border: 1px solid rgba(72, 53, 36, 0.12);
      box-shadow: var(--shadow);
      position: relative;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      right: -56px;
      top: -46px;
      width: 220px;
      height: 220px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(15,118,110,0.16), rgba(15,118,110,0));
      pointer-events: none;
    }}
    .eyebrow {{
      margin: 0 0 12px;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.76rem;
      font-weight: 700;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(2rem, 3.5vw, 3.4rem);
      line-height: 0.95;
      max-width: 12ch;
    }}
    .lede {{
      margin: 12px 0 0;
      color: var(--muted);
      max-width: 44ch;
      line-height: 1.55;
      font-size: 0.98rem;
    }}
    .hero-grid {{
      display: grid;
      grid-template-columns: 1.5fr 0.8fr;
      gap: 18px;
      align-items: end;
    }}
    .hero-summary {{
      background: rgba(255,255,255,0.66);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
    }}
    .hero-summary strong {{
      display: block;
      font-size: 1.02rem;
      margin-bottom: 4px;
    }}
    .hero-summary p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: space-between;
      align-items: center;
      margin-top: 24px;
    }}
    .tabs, .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      cursor: pointer;
      font: inherit;
      transition: transform 160ms ease, box-shadow 160ms ease, background 160ms ease;
    }}
    .tab-button {{
      padding: 13px 20px;
      background: rgba(255,255,255,0.74);
      color: var(--ink);
      border: 1px solid var(--line);
      font-weight: 700;
    }}
    .tab-button.is-active {{
      background: var(--accent);
      color: #fff;
      box-shadow: 0 12px 30px rgba(15, 118, 110, 0.22);
    }}
    .action-button {{
      padding: 11px 16px;
      background: var(--panel-strong);
      color: var(--ink);
      border: 1px solid var(--line);
    }}
    .action-button.primary {{
      background: var(--accent-2);
      color: #fff;
    }}
    .export-wrap {{
      position: relative;
    }}
    .export-menu {{
      position: absolute;
      right: 0;
      top: calc(100% + 10px);
      width: min(290px, 82vw);
      background: rgba(255, 250, 242, 0.98);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 10px;
      display: none;
      z-index: 10;
    }}
    .export-menu.is-open {{
      display: block;
    }}
    .export-item {{
      width: 100%;
      text-align: left;
      padding: 12px 13px;
      border-radius: 14px;
      background: transparent;
      border: 0;
      color: var(--ink);
    }}
    .export-item:hover {{
      background: rgba(15,118,110,0.08);
    }}
    .export-item strong {{
      display: block;
      font-size: 0.95rem;
      margin-bottom: 2px;
    }}
    .export-item span {{
      color: var(--muted);
      font-size: 0.87rem;
      line-height: 1.4;
    }}
    button:hover {{
      transform: translateY(-1px);
    }}
    .toolbar-note {{
      width: 100%;
      margin: 2px 0 0;
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .copy-feedback {{
      color: var(--muted);
      font-size: 0.9rem;
      min-height: 1.2em;
    }}
    .window {{
      display: none;
      margin-top: 22px;
    }}
    .window.is-active {{
      display: block;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 18px;
    }}
    .panel {{
      grid-column: span 12;
      background: var(--panel);
      border: 1px solid rgba(72, 53, 36, 0.12);
      border-radius: 24px;
      box-shadow: var(--shadow);
      padding: 22px;
      backdrop-filter: blur(10px);
    }}
    .panel.hero-panel {{
      padding-bottom: 26px;
    }}
    .section-kicker {{
      margin: 0 0 10px;
      color: var(--accent-2);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.72rem;
      font-weight: 700;
    }}
    .window-title {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: space-between;
      align-items: end;
    }}
    .window-title p {{
      margin: 10px 0 0;
      color: var(--muted);
      max-width: 64ch;
      line-height: 1.55;
    }}
    .delta-badge {{
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.72);
      border: 1px solid var(--line);
      font-weight: 700;
      white-space: nowrap;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin-top: 20px;
    }}
    .headline-band {{
      margin-top: 18px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      padding: 16px 18px;
      background: linear-gradient(135deg, rgba(15,118,110,0.10), rgba(180,83,9,0.08));
      border: 1px solid var(--line);
      border-radius: 18px;
    }}
    .headline-band strong {{
      font-size: 1.08rem;
      line-height: 1.35;
    }}
    .headline-band span {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .badge-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }}
    .summary-badge {{
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.76);
      border: 1px solid var(--line);
      font-size: 0.9rem;
      color: var(--ink);
    }}
    .summary-badge strong {{
      margin-right: 6px;
    }}
    .spotlight-card {{
      margin-top: 16px;
      padding: 18px;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(180,83,9,0.11), rgba(15,118,110,0.09));
      border: 1px solid var(--line);
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 14px;
      align-items: end;
    }}
    .spotlight-card h3 {{
      margin: 0 0 6px;
      font-size: 1rem;
    }}
    .spotlight-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
    }}
    .spotlight-kpis {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .spotlight-kpi {{
      background: rgba(255,255,255,0.7);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
    }}
    .spotlight-kpi strong {{
      display: block;
      font-size: 1rem;
      margin-bottom: 4px;
    }}
    .spotlight-kpi span {{
      color: var(--muted);
      font-size: 0.85rem;
    }}
    .metric {{
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
    }}
    .metric .label {{
      display: block;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.8rem;
    }}
    .metric .value {{
      display: block;
      margin-top: 10px;
      font-size: clamp(1.35rem, 2vw, 2.2rem);
      line-height: 1.05;
    }}
    .metric .hint {{
      display: block;
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }}
    .split {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .section-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .section-header h2, .section-header h3 {{
      margin: 0;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }}
    .detail-toggle {{
      padding: 10px 14px;
      background: rgba(255,255,255,0.74);
      border: 1px solid var(--line);
      color: var(--ink);
      font-size: 0.92rem;
    }}
    .detail-section[hidden] {{
      display: none;
    }}
    .kpi {{
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    .kpi strong {{
      display: block;
      font-size: 1.06rem;
      margin-bottom: 4px;
    }}
    .kpi span {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .chart-card {{
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }}
    .chart-card.chart-wide {{
      grid-column: 1 / -1;
    }}
    .chart-card h3 {{
      margin: 0 0 10px;
      font-size: 1rem;
    }}
    .chart-svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .chart-empty {{
      color: var(--muted);
      font-size: 0.95rem;
      padding: 12px 0 6px;
    }}
    .empty-showcase {{
      background: linear-gradient(135deg, rgba(15,118,110,0.08), rgba(180,83,9,0.06));
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      color: var(--ink);
    }}
    .empty-showcase strong {{
      display: block;
      margin-bottom: 6px;
      font-size: 1rem;
    }}
    .empty-showcase p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
    }}
    .rhythm-card {{
      padding: 18px;
      border-radius: 18px;
      background: linear-gradient(135deg, rgba(15,118,110,0.09), rgba(255,255,255,0.78));
      border: 1px solid var(--line);
    }}
    .rhythm-card h3 {{
      margin: 0 0 8px;
      font-size: 1rem;
    }}
    .rhythm-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
    }}
    .rhythm-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }}
    .rhythm-meta span {{
      padding: 9px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.74);
      border: 1px solid var(--line);
      font-size: 0.9rem;
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    .project-drilldown {{
      display: grid;
      gap: 16px;
    }}
    .project-tab-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .project-tab-button {{
      padding: 10px 14px;
      background: rgba(255,255,255,0.72);
      color: var(--ink);
      border: 1px solid var(--line);
      font-weight: 700;
    }}
    .project-tab-button.is-active {{
      background: var(--accent);
      color: #fff;
      box-shadow: 0 12px 30px rgba(15, 118, 110, 0.18);
    }}
    .project-panel {{
      display: none;
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
    }}
    .project-panel.is-active {{
      display: block;
    }}
    .project-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }}
    .project-meta p {{
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.5;
      max-width: 54ch;
    }}
    .project-stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }}
    .project-stat {{
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    .project-stat strong {{
      display: block;
      font-size: 1.05rem;
      margin-bottom: 4px;
    }}
    .project-stat span {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    ul {{
      margin: 0;
      padding-left: 1.1rem;
    }}
    li {{
      margin: 0 0 10px;
      line-height: 1.5;
    }}
    .takeaway-list {{
      margin: 0;
      padding-left: 1.1rem;
    }}
    .takeaway-list li:last-child {{
      margin-bottom: 0;
    }}
    .footer {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 0.9rem;
      text-align: right;
    }}
    .print-note {{
      display: none;
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    @media (max-width: 960px) {{
      .hero-grid, .metric-grid, .split, .chart-grid, .kpi-grid, .project-stats, .spotlight-card, .spotlight-kpis {{ grid-template-columns: 1fr; }}
    }}
    @media print {{
      @page {{
        margin: 12mm;
      }}
      body {{
        background: #fff;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
      .page {{
        width: auto;
        padding: 0;
      }}
      .hero {{
        margin-bottom: 8mm;
      }}
      .hero::after {{
        display: none;
      }}
      .hero, .panel {{
        box-shadow: none;
        backdrop-filter: none;
        break-inside: avoid;
        page-break-inside: avoid;
      }}
      .panel {{
        margin-bottom: 6mm;
      }}
      .chart-grid, .split, .kpi-grid {{
        grid-template-columns: 1fr !important;
      }}
      .chart-card.chart-wide {{
        grid-column: auto;
      }}
      .table-wrap {{
        overflow: visible;
      }}
      .detail-section[hidden] {{
        display: block !important;
      }}
      .tabs, .actions, .toolbar-note, .detail-toggle {{
        display: none;
      }}
      .print-note {{
        display: block;
      }}
      .window {{
        display: none !important;
      }}
      .window.is-active {{
        display: block !important;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <p class="eyebrow">Codex Stats</p>
      <div class="hero-grid">
        <div>
          <h1>Codex usage at a glance.</h1>
          <p class="lede">Switch ranges, review the stats, and export the active view if you need to share it.</p>
        </div>
        <div class="hero-summary">
          <strong data-active-title>Range</strong>
          <p data-active-description>The selected tab updates the full page.</p>
        </div>
      </div>
      <div class="toolbar">
        <div class="tabs">{tab_buttons}</div>
        <div class="actions">
          <button class="action-button" type="button" data-action="copy-summary">Copy Summary</button>
          <span class="copy-feedback" data-copy-feedback></span>
          <div class="export-wrap">
            <button class="action-button primary" type="button" data-action="toggle-export">Export</button>
            <div class="export-menu" data-export-menu>
              <button class="export-item" type="button" data-action="pdf">
                <strong>Download PDF</strong>
                <span>Best for printing or sending the active view as a full report.</span>
              </button>
              <button class="export-item" type="button" data-jpg="summary-card">
                <strong>Summary JPG</strong>
                <span>Best for a quick share card with headline metrics.</span>
              </button>
              <button class="export-item" type="button" data-jpg="cost-card">
                <strong>Cost JPG</strong>
                <span>Best for cost reviews and spend snapshots.</span>
              </button>
              <button class="export-item" type="button" data-jpg="focus-card">
                <strong>Focus JPG</strong>
                <span>Best for showing anomalies and next steps.</span>
              </button>
              <button class="export-item" type="button" data-jpg="projects-card">
                <strong>Projects JPG</strong>
                <span>Best for README embeds and project-share summaries.</span>
              </button>
              <button class="export-item" type="button" data-jpg="heatmap-card">
                <strong>Heatmap JPG</strong>
                <span>Best for showing when work happens across the week.</span>
              </button>
            </div>
          </div>
        </div>
        <p class="toolbar-note">Generated {escape(generated_at)}</p>
      </div>
      <p class="print-note" data-print-note>PDF export prints the active tab as a report.</p>
    </section>
    {window_sections}
    <div class="footer">Generated by codex-stats</div>
  </main>
  <script>
    const dashboardAssets = {assets_json};
    const dashboardSummaries = {summaries_json};
    const tabs = Array.from(document.querySelectorAll("[data-window]"));
    const windows = Array.from(document.querySelectorAll(".window"));
    const exportWrap = document.querySelector(".export-wrap");
    const exportMenu = document.querySelector("[data-export-menu]");
    const activeTitle = document.querySelector("[data-active-title]");
    const activeDescription = document.querySelector("[data-active-description]");
    const printNote = document.querySelector("[data-print-note]");
    const copyFeedback = document.querySelector("[data-copy-feedback]");
    let activeWindow = tabs[0]?.dataset.window || "";
    let expandedForPrint = [];

    function setActiveWindow(key) {{
      activeWindow = key;
      tabs.forEach((button) => {{
        button.classList.toggle("is-active", button.dataset.window === key);
      }});
      windows.forEach((section) => {{
        section.classList.toggle("is-active", section.dataset.window === key);
      }});
      document.title = `Codex Stats Dashboard - ${{
        tabs.find((button) => button.dataset.window === key)?.textContent || "Stats"
      }}`;
      const activeSection = windows.find((section) => section.dataset.window === key);
      const heading = activeSection?.querySelector(".window-title h2")?.textContent || "Range";
      const description = activeSection?.querySelector(".window-title p")?.textContent || "The selected tab updates the full page.";
      const generatedAt = {json.dumps(generated_at)};
      if (activeTitle) {{
        activeTitle.textContent = heading;
      }}
      if (activeDescription) {{
        activeDescription.textContent = description;
      }}
      if (printNote) {{
        printNote.textContent = `PDF export will print ${{heading}} with expanded details. Generated ${{generatedAt}}.`;
      }}
      exportMenu?.classList.remove("is-open");
      if (copyFeedback) {{
        copyFeedback.textContent = "";
      }}
    }}

    function beforePrint() {{
      const activeSection = windows.find((section) => section.dataset.window === activeWindow);
      expandedForPrint = [];
      activeSection?.querySelectorAll(".detail-section").forEach((section) => {{
        const toggleId = section.id;
        const toggle = activeSection.querySelector(`[data-toggle-details="${{toggleId}}"]`);
        expandedForPrint.push({{
          id: toggleId,
          hidden: section.hidden,
          expanded: toggle?.getAttribute("aria-expanded") || "false",
          label: toggle?.textContent || "Show details",
        }});
        section.hidden = false;
        if (toggle) {{
          toggle.setAttribute("aria-expanded", "true");
          toggle.textContent = "Hide details";
        }}
      }});
    }}

    function afterPrint() {{
      const activeSection = windows.find((section) => section.dataset.window === activeWindow);
      expandedForPrint.forEach((item) => {{
        const section = activeSection?.querySelector(`#${{item.id}}`);
        const toggle = activeSection?.querySelector(`[data-toggle-details="${{item.id}}"]`);
        if (section) {{
          section.hidden = item.hidden;
        }}
        if (toggle) {{
          toggle.setAttribute("aria-expanded", item.expanded);
          toggle.textContent = item.label;
        }}
      }});
      expandedForPrint = [];
    }}

    async function downloadJpg(assetKey) {{
      const content = dashboardAssets[activeWindow]?.[assetKey];
      if (!content) {{
        return;
      }}
      const blob = new Blob([content], {{ type: "image/svg+xml;charset=utf-8" }});
      const url = URL.createObjectURL(blob);
      try {{
        const image = new Image();
        const loaded = new Promise((resolve, reject) => {{
          image.onload = resolve;
          image.onerror = reject;
        }});
        image.src = url;
        await loaded;

        const canvas = document.createElement("canvas");
        const width = image.naturalWidth || 1200;
        const height = image.naturalHeight || 630;
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        if (!context) {{
          return;
        }}
        context.fillStyle = "#fffaf2";
        context.fillRect(0, 0, width, height);
        context.drawImage(image, 0, 0, width, height);

        const jpgUrl = canvas.toDataURL("image/jpeg", 0.94);
        const link = document.createElement("a");
        link.href = jpgUrl;
        link.download = `codex-stats-${{activeWindow}}-${{assetKey}}.jpg`;
        document.body.appendChild(link);
        link.click();
        link.remove();
      }} finally {{
        URL.revokeObjectURL(url);
      }}
    }}

    async function copySummary() {{
      const content = dashboardSummaries[activeWindow];
      if (!content) {{
        if (copyFeedback) {{
          copyFeedback.textContent = "No summary available.";
        }}
        return;
      }}
      try {{
        if (navigator.clipboard?.writeText) {{
          await navigator.clipboard.writeText(content);
        }} else {{
          const textarea = document.createElement("textarea");
          textarea.value = content;
          textarea.setAttribute("readonly", "readonly");
          textarea.style.position = "absolute";
          textarea.style.left = "-9999px";
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand("copy");
          textarea.remove();
        }}
        if (copyFeedback) {{
          copyFeedback.textContent = "Summary copied.";
        }}
      }} catch (error) {{
        if (copyFeedback) {{
          copyFeedback.textContent = "Copy failed.";
        }}
      }}
    }}

    tabs.forEach((button) => {{
      button.addEventListener("click", () => setActiveWindow(button.dataset.window));
    }});
    document.querySelector('[data-action="toggle-export"]')?.addEventListener("click", () => {{
      exportMenu?.classList.toggle("is-open");
    }});
    document.querySelector('[data-action="copy-summary"]')?.addEventListener("click", copySummary);
    document.querySelector('[data-action="pdf"]')?.addEventListener("click", () => {{
      exportMenu?.classList.remove("is-open");
      beforePrint();
      window.print();
    }});
    window.addEventListener("beforeprint", beforePrint);
    window.addEventListener("afterprint", afterPrint);
    document.querySelectorAll("[data-jpg]").forEach((button) => {{
      button.addEventListener("click", async () => {{
        exportMenu?.classList.remove("is-open");
        await downloadJpg(button.dataset.jpg);
      }});
    }});
    document.querySelectorAll("[data-toggle-details]").forEach((button) => {{
      button.addEventListener("click", () => {{
        const target = document.getElementById(button.dataset.toggleDetails);
        const expanded = button.getAttribute("aria-expanded") === "true";
        button.setAttribute("aria-expanded", expanded ? "false" : "true");
        button.textContent = expanded ? "Show details" : "Hide details";
        if (target) {{
          target.hidden = expanded;
        }}
      }});
    }});
    document.querySelectorAll(".project-drilldown").forEach((drilldown) => {{
      const buttons = Array.from(drilldown.querySelectorAll("[data-project-target]"));
      const panels = Array.from(drilldown.querySelectorAll("[data-project-panel]"));
      function setActiveProject(projectId) {{
        buttons.forEach((button) => {{
          button.classList.toggle("is-active", button.dataset.projectTarget === projectId);
        }});
        panels.forEach((panel) => {{
          panel.classList.toggle("is-active", panel.dataset.projectPanel === projectId);
        }});
      }}
      buttons.forEach((button) => {{
        button.addEventListener("click", () => setActiveProject(button.dataset.projectTarget));
      }});
      if (buttons.length) {{
        setActiveProject(buttons[0].dataset.projectTarget);
      }}
    }});
    document.addEventListener("click", (event) => {{
      if (exportWrap && !exportWrap.contains(event.target)) {{
        exportMenu?.classList.remove("is-open");
      }}
    }});
    setActiveWindow(activeWindow);
  </script>
</body>
</html>
"""


def format_report_markdown(report: ReportData) -> str:
    delta_pct = "n/a" if report.comparison.total_tokens_delta_pct is None else f"{report.comparison.total_tokens_delta_pct:+.1f}%"
    title = f"Codex Stats {report.period.title()} Report"
    if report.project_name:
        title = f"{title}: {report.project_name}"
    lines = [
        f"# {title}",
        "",
        f"- Total tokens: `{report.summary.total_tokens:,}`",
        f"- Requests: `{report.summary.requests}`",
        f"- Estimated cost: `${report.summary.estimated_cost_usd:.2f}`",
        f"- Top model: `{report.summary.top_model or 'unknown'}`",
        f"- Trend vs previous window: `{delta_pct}`",
    ]
    if report.project_name is None:
        lines.extend(["", "## Top Projects", ""])
        if report.projects:
            for entry in report.projects:
                lines.append(f"- `{entry.name}`: `{entry.total_tokens:,}` tokens, `{entry.requests}` requests, `${entry.estimated_cost_usd:.2f}`")
        else:
            lines.append("- No data")
    lines.extend(["", "## Top Sessions", ""])
    if report.top_sessions:
        for entry in report.top_sessions:
            lines.append(f"- `{entry.project_name}` / `{entry.model or 'unknown'}`: `{entry.total_tokens:,}` tokens, `{entry.requests}` requests")
    else:
        lines.append("- No data")
    lines.extend(
        [
            "",
            "## Insights",
            "",
            f"- Avg/request: `{report.insights.average_tokens_per_request:,.0f}`",
            f"- Cache ratio: `{_fmt_percent(report.insights.cache_ratio)}`",
            f"- Anomalies: {', '.join(report.insights.anomalies) if report.insights.anomalies else 'none'}",
            f"- Suggestion: {report.insights.suggestion}",
        ]
    )
    if report.insights.recommendations:
        lines.extend(["", "## Recommended Actions", ""])
        for recommendation in report.insights.recommendations:
            lines.append(f"- {recommendation}")
    return "\n".join(lines)


def format_report_html(report: ReportData, daily_points: list[DailyPoint] | None = None) -> str:
    title = f"Codex Stats {report.period.title()} Report"
    if report.project_name:
        title = f"{title}: {report.project_name}"
    delta_pct = "n/a" if report.comparison.total_tokens_delta_pct is None else f"{report.comparison.total_tokens_delta_pct:+.1f}%"
    delta_color = "var(--warn)" if delta_pct.startswith("+") else "var(--good)"
    daily_points = daily_points or []
    projects_html = ""
    if report.project_name is None:
        if report.projects:
            project_rows = "".join(
                f"""
                <tr>
                  <td>{escape(entry.name)}</td>
                  <td>{entry.sessions}</td>
                  <td>{entry.requests}</td>
                  <td>{entry.total_tokens:,}</td>
                  <td>${entry.estimated_cost_usd:.2f}</td>
                </tr>
                """
                for entry in report.projects
            )
        else:
            project_rows = '<tr><td colspan="5">No data</td></tr>'
        projects_html = f"""
        <section class="panel">
          <div class="section-header">
            <h2>Top Projects</h2>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Sessions</th>
                  <th>Requests</th>
                  <th>Tokens</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>{project_rows}</tbody>
            </table>
          </div>
        </section>
        """

    if report.top_sessions:
        top_rows = "".join(
            f"""
            <tr>
              <td>{escape(entry.project_name)}</td>
              <td>{escape(entry.model or 'unknown')}</td>
              <td>{entry.requests}</td>
              <td>{entry.total_tokens:,}</td>
              <td>${entry.estimated_cost_usd:.2f}</td>
            </tr>
            """
            for entry in report.top_sessions
        )
    else:
        top_rows = '<tr><td colspan="5">No data</td></tr>'

    anomalies_html = "".join(f"<li>{escape(item)}</li>" for item in report.insights.anomalies) or "<li>none</li>"
    recommendations_html = "".join(f"<li>{escape(item)}</li>" for item in report.insights.recommendations) or "<li>none</li>"
    token_trend_svg = _svg_line_chart(
        [(point.day[5:], float(point.total_tokens)) for point in daily_points],
        stroke="#0f766e",
        fill="rgba(15, 118, 110, 0.12)",
        value_formatter=lambda value: f"{int(value):,}",
    )
    cost_trend_svg = _svg_line_chart(
        [(point.day[5:], float(point.estimated_cost_usd)) for point in daily_points],
        stroke="#b45309",
        fill="rgba(180, 83, 9, 0.14)",
        value_formatter=lambda value: f"${value:.2f}",
    )
    project_share_svg = _svg_bar_chart(
        [(entry.name, float(entry.total_tokens)) for entry in report.projects[:5]],
        bar_color="#0f766e",
        value_formatter=lambda value: f"{int(value):,}",
        empty_label="No project breakdown for this scoped report.",
    )
    session_share_svg = _svg_bar_chart(
        [(f"{entry.project_name} / {entry.model or 'unknown'}", float(entry.total_tokens)) for entry in report.top_sessions[:5]],
        bar_color="#b45309",
        value_formatter=lambda value: f"{int(value):,}",
        empty_label="No top session data available.",
    )
    heatmap_svg = _svg_heatmap_chart(report.activity_heatmap)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f3efe7;
      --panel: rgba(255, 252, 247, 0.92);
      --panel-strong: #fffaf1;
      --ink: #1f1a17;
      --muted: #6d645d;
      --line: rgba(72, 53, 36, 0.16);
      --accent: #0f766e;
      --accent-2: #b45309;
      --good: #166534;
      --warn: #b45309;
      --shadow: 0 20px 60px rgba(75, 56, 40, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.15), transparent 32%),
        radial-gradient(circle at top right, rgba(180, 83, 9, 0.14), transparent 28%),
        linear-gradient(180deg, #f8f3ea 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    .page {{
      width: min(1120px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 32px 0 56px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255,255,255,0.85), rgba(255,248,238,0.92));
      border: 1px solid rgba(72, 53, 36, 0.12);
      border-radius: 28px;
      box-shadow: var(--shadow);
      padding: 32px;
      position: relative;
      overflow: hidden;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -90px -90px auto;
      width: 240px;
      height: 240px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(15,118,110,0.20), rgba(15,118,110,0));
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 0.75rem;
      color: var(--accent);
      margin-bottom: 12px;
      font-weight: 700;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(2rem, 4vw, 3.7rem);
      line-height: 0.98;
      max-width: 11ch;
    }}
    .hero-grid {{
      display: grid;
      grid-template-columns: 1.4fr 1fr;
      gap: 24px;
      margin-top: 28px;
      align-items: end;
    }}
    .lede {{
      margin: 0;
      max-width: 58ch;
      color: var(--muted);
      font-size: 1.02rem;
      line-height: 1.65;
    }}
    .hero-meta {{
      display: grid;
      gap: 12px;
      justify-items: start;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.7);
      font-size: 0.95rem;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 18px;
      margin-top: 20px;
    }}
    .panel {{
      grid-column: span 12;
      background: var(--panel);
      border: 1px solid rgba(72, 53, 36, 0.12);
      border-radius: 24px;
      box-shadow: var(--shadow);
      padding: 22px;
      backdrop-filter: blur(10px);
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin-top: 18px;
    }}
    .metric {{
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
    }}
    .metric .label {{
      color: var(--muted);
      font-size: 0.84rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .metric .value {{
      display: block;
      margin-top: 8px;
      font-size: clamp(1.35rem, 2vw, 2.2rem);
      line-height: 1.05;
    }}
    .metric .hint {{
      display: block;
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .split {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .section-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 16px;
    }}
    h2 {{
      margin: 0;
      font-size: 1.35rem;
    }}
    .delta {{
      font-weight: 700;
      color: {delta_color};
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .kpi {{
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    .kpi strong {{
      display: block;
      font-size: 1.05rem;
      margin-bottom: 4px;
    }}
    .kpi span {{
      color: var(--muted);
      font-size: 0.92rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    .chart-card {{
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }}
    .chart-card.chart-wide {{
      grid-column: 1 / -1;
    }}
    .chart-card h3 {{
      margin: 0 0 10px;
      font-size: 1rem;
    }}
    .chart-svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .chart-empty {{
      color: var(--muted);
      font-size: 0.95rem;
      padding: 12px 0 6px;
    }}
    .list-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
    }}
    ul {{
      margin: 0;
      padding-left: 1.1rem;
    }}
    li {{
      margin: 0 0 10px;
      line-height: 1.5;
    }}
    .footer {{
      margin-top: 18px;
      color: var(--muted);
      font-size: 0.9rem;
      text-align: right;
    }}
    @media (max-width: 900px) {{
      .hero-grid, .split, .list-grid, .metrics, .chart-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="eyebrow">Codex Stats</div>
      <h1>{escape(title)}</h1>
      <div class="hero-grid">
        <p class="lede">A standalone usage snapshot for {escape(report.project_name or "all tracked projects")}, covering token volume, cost pressure, top sessions, and the most actionable insights from the current reporting window.</p>
        <div class="hero-meta">
          <div class="pill"><strong>Period</strong> <span>{escape(report.period.title())}</span></div>
          <div class="pill"><strong>Top model</strong> <span>{escape(report.summary.top_model or "unknown")}</span></div>
          <div class="pill"><strong>Trend</strong> <span>{escape(delta_pct)}</span></div>
        </div>
      </div>
      <div class="metrics">
        <div class="metric">
          <span class="label">Total Tokens</span>
          <strong class="value">{report.summary.total_tokens:,}</strong>
          <span class="hint">{report.summary.requests} requests across {report.summary.sessions} sessions</span>
        </div>
        <div class="metric">
          <span class="label">Estimated Cost</span>
          <strong class="value">${report.summary.estimated_cost_usd:.2f}</strong>
          <span class="hint">Projected month ${report.costs.projected_monthly_cost_usd:.2f}</span>
        </div>
        <div class="metric">
          <span class="label">Avg per Request</span>
          <strong class="value">{report.summary.average_tokens_per_request:,.0f}</strong>
          <span class="hint">{report.summary.tokens_per_minute:,.0f} tokens per minute</span>
        </div>
        <div class="metric">
          <span class="label">Cache Ratio</span>
          <strong class="value">{escape(_fmt_percent(report.summary.cache_ratio))}</strong>
          <span class="hint">Median session {_fmt_minutes(report.summary.median_session_duration_minutes)}</span>
        </div>
      </div>
    </section>

    <div class="grid">
      <section class="panel">
        <div class="section-header">
          <h2>Window Comparison</h2>
          <span class="delta">{escape(delta_pct)}</span>
        </div>
        <div class="kpis">
          <div class="kpi"><strong>{report.comparison.current.total_tokens:,}</strong><span>Current window tokens</span></div>
          <div class="kpi"><strong>{report.comparison.previous.total_tokens:,}</strong><span>Previous window tokens</span></div>
          <div class="kpi"><strong>{report.comparison.total_tokens_delta:+,}</strong><span>Token delta</span></div>
          <div class="kpi"><strong>{report.comparison.requests_delta:+d}</strong><span>Request delta</span></div>
          <div class="kpi"><strong>${report.comparison.cost_delta_usd:+.2f}</strong><span>Cost delta</span></div>
          <div class="kpi"><strong>{escape(report.summary.top_model or "unknown")}</strong><span>Most used model</span></div>
        </div>
      </section>

      <section class="panel">
        <div class="section-header">
          <h2>Work Patterns</h2>
        </div>
        <div class="kpis">
          <div class="kpi"><strong>{_fmt_minutes(report.summary.average_session_duration_minutes)}</strong><span>Average session length</span></div>
          <div class="kpi"><strong>{_fmt_minutes(report.summary.median_session_duration_minutes)}</strong><span>Median session length</span></div>
          <div class="kpi"><strong>{report.summary.requests_per_session:.1f}</strong><span>Requests per session</span></div>
          <div class="kpi"><strong>{report.summary.median_tokens_per_session:,.0f}</strong><span>Median tokens per session</span></div>
          <div class="kpi"><strong>{escape(_fmt_percent(report.summary.project_concentration_top1_pct))}</strong><span>Top project concentration</span></div>
          <div class="kpi"><strong>{escape(_fmt_percent(report.summary.project_concentration_top3_pct))}</strong><span>Top 3 project concentration</span></div>
          <div class="kpi"><strong>{report.summary.longest_active_streak_days}</strong><span>Longest active streak</span></div>
          <div class="kpi"><strong>{escape(_fmt_percent(report.summary.model_switching_rate))}</strong><span>Model switching rate</span></div>
        </div>
      </section>

      <section class="panel">
        <div class="section-header">
          <h2>Charts</h2>
        </div>
        <div class="chart-grid">
          <div class="chart-card">
            <h3>Daily Token Trend</h3>
            {token_trend_svg}
          </div>
          <div class="chart-card">
            <h3>Daily Cost Trend</h3>
            {cost_trend_svg}
          </div>
          <div class="chart-card">
            <h3>Project Share</h3>
            {project_share_svg}
          </div>
          <div class="chart-card">
            <h3>Top Sessions by Tokens</h3>
            {session_share_svg}
          </div>
          <div class="chart-card chart-wide">
            <h3>Activity Heatmap</h3>
            {heatmap_svg}
            <div class="chart-empty">Hours are shown in local time.</div>
          </div>
        </div>
      </section>

      {projects_html}

      <section class="panel">
        <div class="section-header">
          <h2>Top Sessions</h2>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Project</th>
                <th>Model</th>
                <th>Requests</th>
                <th>Tokens</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>{top_rows}</tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="section-header">
          <h2>Costs</h2>
        </div>
        <div class="split">
          <div class="kpis">
            <div class="kpi"><strong>${report.costs.today_cost_usd:.2f}</strong><span>Today</span></div>
            <div class="kpi"><strong>${report.costs.week_cost_usd:.2f}</strong><span>Week</span></div>
            <div class="kpi"><strong>${report.costs.month_cost_usd:.2f}</strong><span>Month</span></div>
            <div class="kpi"><strong>${report.costs.highest_session_cost_usd:.2f}</strong><span>Highest session</span></div>
          </div>
          <div class="metric">
            <span class="label">Recommendation</span>
            <strong class="value">{escape(report.insights.suggestion)}</strong>
            <span class="hint">Based on observed cache reuse, request size, and session concentration.</span>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="section-header">
          <h2>Insights</h2>
        </div>
        <div class="list-grid">
          <div>
            <h3>Anomalies</h3>
            <ul>{anomalies_html}</ul>
          </div>
          <div>
            <h3>Recommended Actions</h3>
            <ul>{recommendations_html}</ul>
          </div>
        </div>
      </section>
    </div>

    <div class="footer">Generated by codex-stats</div>
  </main>
</body>
</html>
"""


def format_dashboard_svg_assets(window: DashboardWindow) -> dict[str, str]:
    title = f"Codex Stats {window.label}"
    return {
        "summary-card": _format_summary_card_svg(window, title),
        "cost-card": _format_cost_card_svg(window, title),
        "focus-card": _format_focus_card_svg(window, title),
        "projects-card": _format_projects_card_svg(window, title),
        "heatmap-card": _format_heatmap_card_svg(window, title),
    }


def format_report_svg_assets(report: ReportData, daily_points: list[DailyPoint] | None = None) -> dict[str, str]:
    title = f"Codex Stats {report.period.title()} Report"
    if report.project_name:
        title = f"{title}: {report.project_name}"
    assets = {
        "summary-card": _format_summary_card_svg(report, title),
        "cost-card": _format_cost_card_svg(report, title),
        "focus-card": _format_focus_card_svg(report, title),
        "projects-card": _format_projects_card_svg(report, title),
        "heatmap-card": _format_heatmap_card_svg(report, title),
    }
    return assets


def format_report_svg(report: ReportData, daily_points: list[DailyPoint] | None = None) -> str:
    return format_report_svg_assets(report, daily_points)["summary-card"]


def _format_dashboard_window_section(window: DashboardWindow, *, is_active: bool) -> str:
    delta_pct = "n/a" if window.comparison.total_tokens_delta_pct is None else f"{window.comparison.total_tokens_delta_pct:+.1f}%"
    delta_tone = "var(--warn)" if delta_pct.startswith("+") else "var(--good)"
    headline = f"You spent ${window.summary.estimated_cost_usd:.2f} across {window.summary.requests} requests in {window.label.lower()}."
    if window.key == "all":
        headline = f"You have spent ${window.summary.estimated_cost_usd:.2f} across all recorded Codex usage."
    change_text = (
        f"{window.comparison.total_tokens_delta:+,} tokens versus {window.comparison.previous.label}"
        if window.comparison.previous.total_tokens or window.comparison.total_tokens_delta
        else "No comparable previous window yet."
    )
    token_trend_svg = _svg_line_chart(
        [(point.day[5:], float(point.total_tokens)) for point in window.daily_points],
        stroke="#0f766e",
        fill="rgba(15, 118, 110, 0.12)",
        value_formatter=lambda value: f"{int(value):,}",
    )
    cost_trend_svg = _svg_line_chart(
        [(point.day[5:], float(point.estimated_cost_usd)) for point in window.daily_points],
        stroke="#b45309",
        fill="rgba(180, 83, 9, 0.14)",
        value_formatter=lambda value: f"${value:.2f}",
    )
    projects_svg = _svg_bar_chart(
        [(entry.name, float(entry.total_tokens)) for entry in window.projects[:6]],
        bar_color="#0f766e",
        value_formatter=lambda value: f"{int(value):,}",
        empty_label="No project data available for this view.",
    )
    sessions_svg = _svg_bar_chart(
        [(f"{entry.project_name} / {entry.model or 'unknown'}", float(entry.total_tokens)) for entry in window.top_sessions[:6]],
        bar_color="#b45309",
        value_formatter=lambda value: f"{int(value):,}",
        empty_label="No top session data available for this view.",
    )
    heatmap_svg = _svg_heatmap_chart(window.activity_heatmap)
    project_rows = "".join(
        f"""
        <tr>
          <td>{escape(entry.name)}</td>
          <td>{entry.sessions}</td>
          <td>{entry.requests}</td>
          <td>{entry.total_tokens:,}</td>
          <td>${entry.estimated_cost_usd:.2f}</td>
        </tr>
        """
        for entry in window.projects
    ) or '<tr><td colspan="5">No data</td></tr>'
    top_rows = "".join(
        f"""
        <tr>
          <td>{escape(entry.project_name)}</td>
          <td>{escape(entry.model or 'unknown')}</td>
          <td>{entry.requests}</td>
          <td>{entry.total_tokens:,}</td>
          <td>${entry.estimated_cost_usd:.2f}</td>
        </tr>
        """
        for entry in window.top_sessions
    ) or '<tr><td colspan="5">No data</td></tr>'
    history_rows = "".join(
        f"""
        <tr>
          <td>{escape(_fmt_short_dt(entry.updated_at))}</td>
          <td>{escape(entry.project_name)}</td>
          <td>{escape(entry.model or 'unknown')}</td>
          <td>{entry.requests}</td>
          <td>{entry.total_tokens:,}</td>
          <td>${entry.estimated_cost_usd:.2f}</td>
        </tr>
        """
        for entry in window.history
    ) or '<tr><td colspan="6">No data</td></tr>'
    anomalies_html = "".join(f"<li>{escape(item)}</li>" for item in window.insights.anomalies) or "<li>none</li>"
    recommendations_html = "".join(f"<li>{escape(item)}</li>" for item in window.insights.recommendations) or "<li>none</li>"
    project_drilldown_html = _format_project_drilldown(window)
    badges_html = "".join(
        f'<div class="summary-badge"><strong>{escape(badge.label)}:</strong>{escape(badge.value)}</div>'
        for badge in window.badges
    )
    expensive_session_html = ""
    if window.expensive_session:
        expensive_session_html = f"""
          <div class="spotlight-card">
            <div>
              <h3>Most Expensive Session</h3>
              <p>{escape(window.expensive_session.project_name)} used {escape(window.expensive_session.model or 'unknown')} and drove the highest estimated cost in this view.</p>
            </div>
            <div class="spotlight-kpis">
              <div class="spotlight-kpi"><strong>${window.expensive_session.estimated_cost_usd:.2f}</strong><span>Estimated cost</span></div>
              <div class="spotlight-kpi"><strong>{window.expensive_session.total_tokens:,}</strong><span>Tokens</span></div>
              <div class="spotlight-kpi"><strong>{window.expensive_session.requests}</strong><span>Requests</span></div>
            </div>
          </div>
        """
    return f"""
    <section class="window{' is-active' if is_active else ''}" data-window="{escape(window.key)}">
      <div class="grid">
        <section class="panel hero-panel">
          <p class="section-kicker">Start Here</p>
          <div class="window-title">
            <div>
              <h2>{escape(window.label)}</h2>
              <p>{escape(window.description)}</p>
            </div>
            <div class="delta-badge" style="color: {delta_tone};">{escape(window.comparison_label)}: {escape(delta_pct)}</div>
          </div>
          <div class="headline-band">
            <strong>{escape(headline)}</strong>
            <span>{escape(change_text)}</span>
          </div>
          <div class="badge-row">{badges_html}</div>
          {expensive_session_html}
          <div class="metric-grid">
            <div class="metric">
              <span class="label">Total Tokens</span>
              <strong class="value">{window.summary.total_tokens:,}</strong>
              <span class="hint">{window.summary.requests} requests across {window.summary.sessions} sessions</span>
            </div>
            <div class="metric">
              <span class="label">Estimated Cost</span>
              <strong class="value">${window.summary.estimated_cost_usd:.2f}</strong>
              <span class="hint">Projected month ${window.costs.projected_monthly_cost_usd:.2f}</span>
            </div>
            <div class="metric">
              <span class="label">Avg per Request</span>
              <strong class="value">{window.summary.average_tokens_per_request:,.0f}</strong>
              <span class="hint">Largest session {window.summary.largest_session_tokens:,} tokens</span>
            </div>
            <div class="metric">
              <span class="label">Cache Ratio</span>
              <strong class="value">{escape(_fmt_percent(window.summary.cache_ratio))}</strong>
              <span class="hint">Top model {escape(window.summary.top_model or 'unknown')}</span>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="section-header">
            <div>
              <p class="section-kicker">Biggest Change</p>
              <h2>Comparison</h2>
            </div>
            <strong style="color: {delta_tone};">{escape(delta_pct)}</strong>
          </div>
          <div class="kpi-grid">
            <div class="kpi"><strong>{window.comparison.current.total_tokens:,}</strong><span>{escape(window.comparison.current.label)}</span></div>
            <div class="kpi"><strong>{window.comparison.previous.total_tokens:,}</strong><span>{escape(window.comparison.previous.label)}</span></div>
            <div class="kpi"><strong>{window.comparison.total_tokens_delta:+,}</strong><span>Token delta</span></div>
            <div class="kpi"><strong>{window.comparison.requests_delta:+d}</strong><span>Request delta</span></div>
            <div class="kpi"><strong>${window.comparison.cost_delta_usd:+.2f}</strong><span>Cost delta</span></div>
            <div class="kpi"><strong>{escape(window.insights.suggestion)}</strong><span>Primary recommendation</span></div>
          </div>
        </section>

        <section class="panel">
          <div class="section-header">
            <div>
              <p class="section-kicker">When You Work</p>
              <h2>Work Rhythm</h2>
            </div>
          </div>
          {_format_work_rhythm_card(window)}
        </section>

        <section class="panel">
          <div class="section-header">
            <div>
              <p class="section-kicker">What Changed</p>
              <h2>Key Takeaways</h2>
            </div>
          </div>
          <ul class="takeaway-list">{''.join(f"<li>{escape(item)}</li>" for item in window.takeaways)}</ul>
        </section>

        <section class="panel">
          <div class="section-header">
            <div>
              <p class="section-kicker">Work Shape</p>
              <h2>Work Patterns</h2>
            </div>
          </div>
          <div class="kpi-grid">
            <div class="kpi"><strong>{_fmt_minutes(window.summary.average_session_duration_minutes)}</strong><span>Average session length</span></div>
            <div class="kpi"><strong>{_fmt_minutes(window.summary.median_session_duration_minutes)}</strong><span>Median session length</span></div>
            <div class="kpi"><strong>{window.summary.tokens_per_minute:,.0f}</strong><span>Tokens per minute</span></div>
            <div class="kpi"><strong>{window.summary.requests_per_session:.1f}</strong><span>Requests per session</span></div>
            <div class="kpi"><strong>{window.summary.median_tokens_per_session:,.0f}</strong><span>Median tokens per session</span></div>
            <div class="kpi"><strong>{window.summary.median_requests_per_session:,.1f}</strong><span>Median requests per session</span></div>
            <div class="kpi"><strong>{escape(_fmt_percent(window.summary.project_concentration_top1_pct))}</strong><span>Top project concentration</span></div>
            <div class="kpi"><strong>{escape(_fmt_percent(window.summary.project_concentration_top3_pct))}</strong><span>Top 3 project concentration</span></div>
            <div class="kpi"><strong>{window.summary.longest_active_streak_days}</strong><span>Longest active streak</span></div>
            <div class="kpi"><strong>{escape(_fmt_percent(window.summary.model_switching_rate))}</strong><span>Model switching rate</span></div>
          </div>
        </section>

        <section class="panel">
          <div class="section-header">
            <div>
              <p class="section-kicker">Why It Happened</p>
              <h2>Charts</h2>
            </div>
          </div>
          <div class="chart-grid">
            <div class="chart-card">
              <h3>Token Trend</h3>
              {token_trend_svg}
            </div>
            <div class="chart-card">
              <h3>Cost Trend</h3>
              {cost_trend_svg}
            </div>
            <div class="chart-card">
              <h3>Project Share</h3>
              {projects_svg}
            </div>
            <div class="chart-card">
              <h3>Top Sessions by Tokens</h3>
              {sessions_svg}
            </div>
            <div class="chart-card chart-wide">
              <h3>Activity Heatmap</h3>
              {heatmap_svg}
              <div class="chart-empty">Hours are shown in local time.</div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="section-header">
            <div>
              <p class="section-kicker">What To Look At</p>
              <h2>Costs and Insights</h2>
            </div>
          </div>
          <div class="split">
            <div class="kpi-grid">
              <div class="kpi"><strong>${window.summary.estimated_cost_usd:.2f}</strong><span>{escape(window.summary.label)} total</span></div>
              <div class="kpi"><strong>${window.comparison.current.estimated_cost_usd:.2f}</strong><span>{escape(window.comparison.current.label)} cost</span></div>
              <div class="kpi"><strong>${window.comparison.previous.estimated_cost_usd:.2f}</strong><span>{escape(window.comparison.previous.label)} cost</span></div>
              <div class="kpi"><strong>${window.costs.projected_monthly_cost_usd:.2f}</strong><span>Projected month</span></div>
              <div class="kpi"><strong>${window.costs.highest_session_cost_usd:.2f}</strong><span>Highest session</span></div>
              <div class="kpi"><strong>${window.comparison.cost_delta_usd:+.2f}</strong><span>Window delta</span></div>
            </div>
            <div class="split" style="grid-template-columns: 1fr 1fr;">
              <div class="metric">
                <span class="label">Anomalies</span>
                <ul>{anomalies_html}</ul>
              </div>
              <div class="metric">
                <span class="label">Recommended Actions</span>
                <ul>{recommendations_html}</ul>
                <span class="hint">Possible savings ${window.insights.possible_savings_usd:.2f}</span>
              </div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="section-header">
            <div>
              <p class="section-kicker">Go Deeper</p>
              <h2>Project Drilldown</h2>
            </div>
          </div>
          {project_drilldown_html}
        </section>

        <section class="panel">
          <div class="section-header">
            <div>
              <p class="section-kicker">Details</p>
              <h2>Projects, Sessions, and History</h2>
            </div>
            <button class="detail-toggle" type="button" data-toggle-details="details-{escape(window.key)}" aria-expanded="false">Show details</button>
          </div>
          <div class="detail-section" id="details-{escape(window.key)}" hidden>
            <div class="split">
              <div>
                <div class="section-header">
                  <h3>Top Projects</h3>
                </div>
                <div class="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Sessions</th>
                        <th>Requests</th>
                        <th>Tokens</th>
                        <th>Cost</th>
                      </tr>
                    </thead>
                    <tbody>{project_rows}</tbody>
                  </table>
                </div>
              </div>
              <div>
                <div class="section-header">
                  <h3>Top Sessions</h3>
                </div>
                <div class="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Model</th>
                        <th>Requests</th>
                        <th>Tokens</th>
                        <th>Cost</th>
                      </tr>
                    </thead>
                    <tbody>{top_rows}</tbody>
                  </table>
                </div>
              </div>
            </div>
            <div class="section-header" style="margin-top: 18px;">
              <h3>Recent Sessions</h3>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Updated</th>
                    <th>Project</th>
                    <th>Model</th>
                    <th>Requests</th>
                    <th>Tokens</th>
                    <th>Cost</th>
                  </tr>
                </thead>
                <tbody>{history_rows}</tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    </section>
    """


def _format_project_drilldown(window: DashboardWindow) -> str:
    if not window.project_drilldowns:
        return _format_empty_showcase(
            "No project drilldown yet.",
            "Run a few sessions in at least one project and this section will break out project-specific trends, heatmaps, and top sessions.",
        )
    buttons = []
    panels = []
    for index, drilldown in enumerate(window.project_drilldowns):
        project_id = f"{window.key}-project-{index}"
        buttons.append(
            f'<button class="project-tab-button" type="button" data-project-target="{escape(project_id)}">{escape(drilldown.name)}</button>'
        )
        panels.append(_format_project_panel(project_id, drilldown))
    return (
        '<div class="project-drilldown">'
        f'<div class="project-tab-list">{"".join(buttons)}</div>'
        f'{"".join(panels)}'
        "</div>"
    )


def _format_project_panel(project_id: str, drilldown: ProjectDrilldown) -> str:
    token_trend_svg = _svg_line_chart(
        [(point.day[5:], float(point.total_tokens)) for point in drilldown.daily_points],
        stroke="#0f766e",
        fill="rgba(15, 118, 110, 0.12)",
        value_formatter=lambda value: f"{int(value):,}",
    )
    heatmap_svg = _svg_heatmap_chart(drilldown.activity_heatmap)
    top_rows = "".join(
        f"""
        <tr>
          <td>{escape(entry.model or 'unknown')}</td>
          <td>{entry.requests}</td>
          <td>{entry.total_tokens:,}</td>
          <td>${entry.estimated_cost_usd:.2f}</td>
        </tr>
        """
        for entry in drilldown.top_sessions
    ) or '<tr><td colspan="4">No data</td></tr>'
    history_rows = "".join(
        f"""
        <tr>
          <td>{escape(_fmt_short_dt(entry.updated_at))}</td>
          <td>{escape(entry.model or 'unknown')}</td>
          <td>{entry.requests}</td>
          <td>{entry.total_tokens:,}</td>
          <td>${entry.estimated_cost_usd:.2f}</td>
        </tr>
        """
        for entry in drilldown.history
    ) or '<tr><td colspan="5">No data</td></tr>'
    return f"""
    <div class="project-panel" data-project-panel="{escape(project_id)}">
      <div class="project-meta">
        <div>
          <h3>{escape(drilldown.name)}</h3>
          <p>{escape(drilldown.insights.suggestion)} Possible savings: ${drilldown.insights.possible_savings_usd:.2f}.</p>
        </div>
        <div class="delta-badge">Top model: {escape(drilldown.summary.top_model or 'unknown')}</div>
      </div>
      <div class="metric" style="margin-bottom: 16px;">
        <span class="label">Key Takeaways</span>
        <ul class="takeaway-list">{''.join(f"<li>{escape(item)}</li>" for item in drilldown.takeaways)}</ul>
      </div>
      <div class="project-stats">
        <div class="project-stat"><strong>{drilldown.summary.total_tokens:,}</strong><span>Total tokens</span></div>
        <div class="project-stat"><strong>${drilldown.summary.estimated_cost_usd:.2f}</strong><span>Estimated cost</span></div>
        <div class="project-stat"><strong>{drilldown.summary.requests}</strong><span>Requests</span></div>
        <div class="project-stat"><strong>{escape(_fmt_percent(drilldown.summary.cache_ratio))}</strong><span>Cache ratio</span></div>
      </div>
      <div class="chart-grid">
        <div class="chart-card">
          <h3>Project Token Trend</h3>
          {token_trend_svg}
        </div>
        <div class="chart-card">
          <h3>Project Activity Heatmap</h3>
          {heatmap_svg}
        </div>
      </div>
      <div class="split" style="margin-top: 16px;">
        <div>
          <div class="section-header">
            <h3>Top Sessions in This Project</h3>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Requests</th>
                  <th>Tokens</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>{top_rows}</tbody>
            </table>
          </div>
        </div>
        <div>
          <div class="section-header">
            <h3>Recent Sessions in This Project</h3>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Updated</th>
                  <th>Model</th>
                  <th>Requests</th>
                  <th>Tokens</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>{history_rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
    """


def _format_work_rhythm_card(window: DashboardWindow) -> str:
    meta = []
    if window.work_rhythm.peak_day:
        meta.append(f"<span>Peak day: {escape(window.work_rhythm.peak_day)}</span>")
    if window.work_rhythm.peak_hour:
        meta.append(f"<span>Peak hour: {escape(window.work_rhythm.peak_hour)}</span>")
    meta_html = f'<div class="rhythm-meta">{"".join(meta)}</div>' if meta else ""
    return f"""
    <div class="rhythm-card">
      <h3>{escape(window.work_rhythm.headline)}</h3>
      <p>{escape(window.work_rhythm.detail)}</p>
      {meta_html}
    </div>
    """


def _format_empty_showcase(title: str, detail: str) -> str:
    return f"""
    <div class="empty-showcase">
      <strong>{escape(title)}</strong>
      <p>{escape(detail)}</p>
    </div>
    """


def _format_empty_chart(title: str, detail: str) -> str:
    return f'<div class="chart-empty">{_format_empty_showcase(title, detail)}</div>'


def _format_window_copy_summary(window: DashboardWindow) -> str:
    lines = [
        f"Codex Stats {window.label}",
        f"Tokens: {window.summary.total_tokens:,}",
        f"Requests: {window.summary.requests}",
        f"Estimated cost: ${window.summary.estimated_cost_usd:.2f}",
        f"Top model: {window.summary.top_model or 'unknown'}",
    ]
    if window.takeaways:
        lines.append("Takeaways:")
        lines.extend(f"- {item}" for item in window.takeaways[:3])
    if window.projects:
        top_project = window.projects[0]
        lines.append(
            f"Top project: {top_project.name} with {top_project.total_tokens:,} tokens across {top_project.requests} requests."
        )
    return "\n".join(lines)


def _svg_line_chart(
    points: list[tuple[str, float]],
    *,
    stroke: str,
    fill: str,
    value_formatter,
) -> str:
    if not points:
        return _format_empty_chart("No trend yet.", "Use Codex on more than one day in this window to reveal the trend line.")
    width = 760
    height = 240
    padding_left = 48
    padding_right = 20
    padding_top = 20
    padding_bottom = 38
    values = [value for _, value in points]
    max_value = max(values) if max(values) > 0 else 1.0
    inner_width = width - padding_left - padding_right
    inner_height = height - padding_top - padding_bottom

    def point_x(index: int) -> float:
        if len(points) == 1:
            return padding_left + inner_width / 2
        return padding_left + (index / (len(points) - 1)) * inner_width

    def point_y(value: float) -> float:
        return padding_top + inner_height - (value / max_value) * inner_height

    line_points = " ".join(f"{point_x(index):.1f},{point_y(value):.1f}" for index, (_, value) in enumerate(points))
    area_points = f"{padding_left:.1f},{padding_top + inner_height:.1f} {line_points} {padding_left + inner_width:.1f},{padding_top + inner_height:.1f}"
    labels = "".join(
        f'<text x="{point_x(index):.1f}" y="{height - 12}" text-anchor="middle" font-size="11" fill="#6d645d">{escape(label)}</text>'
        for index, (label, _) in enumerate(points)
    )
    dots = "".join(
        f'<circle cx="{point_x(index):.1f}" cy="{point_y(value):.1f}" r="4" fill="{stroke}"><title>{escape(label)}: {escape(value_formatter(value))}</title></circle>'
        for index, (label, value) in enumerate(points)
    )
    grid = "".join(
        f'<line x1="{padding_left}" y1="{padding_top + step * (inner_height / 3):.1f}" x2="{width - padding_right}" y2="{padding_top + step * (inner_height / 3):.1f}" stroke="rgba(72,53,36,0.12)" stroke-dasharray="4 6" />'
        for step in range(4)
    )
    y_labels = "".join(
        f'<text x="{padding_left - 8}" y="{padding_top + inner_height - step * (inner_height / 3) + 4:.1f}" text-anchor="end" font-size="11" fill="#6d645d">{escape(value_formatter((max_value / 3) * step))}</text>'
        for step in range(4)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Trend chart">'
        f'{grid}'
        f'<polygon points="{area_points}" fill="{fill}" />'
        f'<polyline points="{line_points}" fill="none" stroke="{stroke}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />'
        f'{dots}{labels}{y_labels}</svg>'
    )


def _svg_bar_chart(
    bars: list[tuple[str, float]],
    *,
    bar_color: str,
    value_formatter,
    empty_label: str,
) -> str:
    if not bars:
        return _format_empty_chart("Nothing to rank yet.", empty_label)
    width = 760
    row_height = 34
    padding = 18
    label_width = 170
    bar_max_width = width - (padding * 2) - label_width - 90
    height = padding * 2 + row_height * len(bars)
    max_value = max(value for _, value in bars) if max(value for _, value in bars) > 0 else 1.0
    rows = []
    for index, (label, value) in enumerate(bars):
        y = padding + index * row_height
        bar_width = (value / max_value) * bar_max_width
        rows.append(
            f'<text x="{padding}" y="{y + 20}" font-size="12" fill="#1f1a17">{escape(label)}</text>'
            f'<rect x="{padding + label_width}" y="{y + 6}" width="{bar_max_width:.1f}" height="16" rx="8" fill="rgba(72,53,36,0.08)" />'
            f'<rect x="{padding + label_width}" y="{y + 6}" width="{bar_width:.1f}" height="16" rx="8" fill="{bar_color}" />'
            f'<text x="{padding + label_width + bar_max_width + 10}" y="{y + 19}" font-size="12" fill="#6d645d">{escape(value_formatter(value))}</text>'
        )
    return f'<svg xmlns="http://www.w3.org/2000/svg" class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Bar chart">{"".join(rows)}</svg>'


def _svg_heatmap_chart(cells: list[HeatmapCell]) -> str:
    if not cells:
        return _format_empty_chart("No activity map yet.", "This heatmap fills in after you use Codex across different hours of the day.")
    width = 760
    height = 290
    left = 68
    top = 24
    cell_width = 24
    cell_height = 26
    gap = 4
    max_value = max((cell.total_tokens for cell in cells), default=0) or 1
    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    lookup = {(cell.weekday, cell.hour): cell for cell in cells}
    rects: list[str] = []
    for weekday in range(7):
        for hour in range(24):
            cell = lookup.get((weekday, hour))
            tokens = cell.total_tokens if cell else 0
            sessions = cell.session_count if cell else 0
            ratio = tokens / max_value if max_value else 0.0
            fill = _heatmap_color(ratio)
            x = left + hour * (cell_width + gap)
            y = top + weekday * (cell_height + gap)
            rects.append(
                f'<rect x="{x}" y="{y}" width="{cell_width}" height="{cell_height}" rx="7" fill="{fill}">'
                f'<title>{escape(_heatmap_title(weekday_labels[weekday], hour, sessions, tokens))}</title>'
                f"</rect>"
            )
    hour_labels = "".join(
        f'<text x="{left + hour * (cell_width + gap) + cell_width / 2:.1f}" y="{top - 8}" text-anchor="middle" font-size="10" fill="#6d645d">{hour:02d}</text>'
        for hour in range(24)
    )
    day_labels = "".join(
        f'<text x="{left - 10}" y="{top + weekday * (cell_height + gap) + 17}" text-anchor="end" font-size="12" fill="#6d645d">{label}</text>'
        for weekday, label in enumerate(weekday_labels)
    )
    legend_start_x = 520
    legend_y = 252
    legend = "".join(
        f'<rect x="{legend_start_x + index * 34}" y="{legend_y}" width="24" height="14" rx="7" fill="{_heatmap_color(index / 4)}" />'
        for index in range(5)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Activity heatmap">'
        f'{hour_labels}{day_labels}{"".join(rects)}'
        f'<text x="{legend_start_x}" y="{legend_y - 8}" font-size="11" fill="#6d645d">Lower activity</text>'
        f'{legend}'
        f'<text x="{legend_start_x + (4 * 34) + 24}" y="{legend_y - 8}" text-anchor="end" font-size="11" fill="#6d645d">Higher activity</text>'
        f"</svg>"
    )


def _heatmap_color(ratio: float) -> str:
    if ratio <= 0:
        return "rgba(72,53,36,0.08)"
    if ratio < 0.25:
        return "#d7efe7"
    if ratio < 0.5:
        return "#8ed3c5"
    if ratio < 0.75:
        return "#2ea596"
    return "#0f766e"


def _heatmap_title(day_label: str, hour: int, sessions: int, tokens: int) -> str:
    return f"{day_label} {hour:02d}:00 - {sessions} sessions, {tokens:,} tokens"


def _format_summary_card_svg(report: ReportData, title: str) -> str:
    delta_text = "n/a" if report.comparison.total_tokens_delta_pct is None else f"{report.comparison.total_tokens_delta_pct:+.1f}%"
    anomalies = report.insights.anomalies[:2] or ["No active anomalies"]
    recommendations = report.insights.recommendations[:2] or ["Usage looks healthy."]
    first_action = recommendations[0]
    second_action = recommendations[1] if len(recommendations) > 1 else recommendations[0]
    first_anomaly = anomalies[0]
    second_anomaly = anomalies[1] if len(anomalies) > 1 else anomalies[0]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{escape(title)}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#fbf5ec"/>
      <stop offset="100%" stop-color="#efe2cf"/>
    </linearGradient>
    <linearGradient id="teal" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#115e59"/>
      <stop offset="100%" stop-color="#0f766e"/>
    </linearGradient>
    <linearGradient id="amber" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#b45309"/>
      <stop offset="100%" stop-color="#d97706"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="34" y="28" width="1132" height="574" rx="32" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>

  <circle cx="1056" cy="126" r="118" fill="rgba(15,118,110,0.10)"/>
  <circle cx="1116" cy="206" r="72" fill="rgba(217,119,6,0.10)"/>
  <circle cx="1012" cy="214" r="18" fill="#0f766e"/>
  <circle cx="1066" cy="164" r="18" fill="#d97706"/>
  <circle cx="1120" cy="114" r="18" fill="#0f766e"/>

  <text x="74" y="86" font-size="18" letter-spacing="3" fill="#0f766e">CODEX STATS</text>
  <text x="74" y="150" font-size="60" font-weight="700" fill="#1f1a17">{escape(title)}</text>
  <text x="74" y="194" font-size="24" fill="#6d645d">Compact share card for release notes, README embeds, and social posts.</text>

  <rect x="74" y="226" width="336" height="52" rx="26" fill="rgba(15,118,110,0.08)"/>
  <text x="102" y="258" font-size="20" fill="#134e4a">Top model {escape(report.summary.top_model or "unknown")}</text>
  <rect x="426" y="226" width="190" height="52" rx="26" fill="rgba(180,83,9,0.10)"/>
  <text x="454" y="258" font-size="20" fill="#92400e">Trend {escape(delta_text)}</text>
  <rect x="632" y="226" width="214" height="52" rx="26" fill="rgba(66,48,31,0.06)"/>
  <text x="660" y="258" font-size="20" fill="#4b4036">Cache {escape(_fmt_percent(report.summary.cache_ratio))}</text>

  <rect x="74" y="314" width="240" height="120" rx="24" fill="url(#teal)"/>
  <text x="98" y="350" font-size="16" letter-spacing="2" fill="#d7faf5">TOKENS</text>
  <text x="98" y="397" font-size="40" font-weight="700" fill="#ffffff">{report.summary.total_tokens:,}</text>
  <text x="98" y="423" font-size="18" fill="#d7faf5">{report.summary.sessions} sessions</text>

  <rect x="334" y="314" width="220" height="120" rx="24" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="358" y="350" font-size="16" letter-spacing="2" fill="#6d645d">EST. COST</text>
  <text x="358" y="397" font-size="40" font-weight="700" fill="#1f1a17">${report.summary.estimated_cost_usd:.2f}</text>
  <text x="358" y="423" font-size="18" fill="#6d645d">Projected ${report.costs.projected_monthly_cost_usd:.2f}</text>

  <rect x="574" y="314" width="220" height="120" rx="24" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="598" y="350" font-size="16" letter-spacing="2" fill="#6d645d">REQUESTS</text>
  <text x="598" y="397" font-size="40" font-weight="700" fill="#1f1a17">{report.summary.requests}</text>
  <text x="598" y="423" font-size="18" fill="#6d645d">Largest {report.summary.largest_session_tokens:,}</text>

  <rect x="814" y="314" width="312" height="120" rx="24" fill="url(#amber)"/>
  <text x="838" y="350" font-size="16" letter-spacing="2" fill="#ffedd5">AVG / REQUEST</text>
  <text x="838" y="397" font-size="40" font-weight="700" fill="#ffffff">{report.summary.average_tokens_per_request:,.0f}</text>
  <text x="838" y="423" font-size="18" fill="#ffedd5">{escape(report.insights.suggestion[:34])}</text>

  <rect x="74" y="466" width="492" height="94" rx="24" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="98" y="500" font-size="18" letter-spacing="2" fill="#8a4b0f">ANOMALIES</text>
  <text x="98" y="530" font-size="20" fill="#8a4b0f">• {escape(first_anomaly)}</text>
  <text x="98" y="556" font-size="20" fill="#8a4b0f">• {escape(second_anomaly)}</text>

  <rect x="592" y="466" width="534" height="94" rx="24" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="616" y="500" font-size="18" letter-spacing="2" fill="#4b4036">DO NEXT</text>
  <text x="616" y="530" font-size="20" fill="#4b4036">• {escape(first_action)}</text>
  <text x="616" y="556" font-size="20" fill="#4b4036">• {escape(second_action)}</text>

  <text x="1128" y="590" text-anchor="end" font-size="18" fill="#6d645d">Generated by codex-stats</text>
</svg>"""


def _format_cost_card_svg(report: ReportData | DashboardWindow, title: str) -> str:
    if isinstance(report, DashboardWindow):
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{escape(title)} cost card">
  <rect width="1200" height="630" fill="#f7efe2"/>
  <rect x="40" y="36" width="1120" height="558" rx="32" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="76" y="92" font-size="18" letter-spacing="3" fill="#b45309">CODEX STATS</text>
  <text x="76" y="150" font-size="56" font-weight="700" fill="#1f1a17">Cost Snapshot</text>
  <text x="76" y="194" font-size="24" fill="#6d645d">{escape(title)}</text>

  <rect x="76" y="244" width="254" height="154" rx="28" fill="#b45309"/>
  <text x="104" y="286" font-size="16" letter-spacing="2" fill="#ffedd5">WINDOW TOTAL</text>
  <text x="104" y="348" font-size="48" font-weight="700" fill="#ffffff">${report.summary.estimated_cost_usd:.2f}</text>
  <text x="104" y="378" font-size="20" fill="#ffedd5">{escape(report.summary.label.title())}</text>

  <rect x="348" y="244" width="254" height="154" rx="28" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="376" y="286" font-size="16" letter-spacing="2" fill="#6d645d">CURRENT COMPARE</text>
  <text x="376" y="348" font-size="48" font-weight="700" fill="#1f1a17">${report.comparison.current.estimated_cost_usd:.2f}</text>
  <text x="376" y="378" font-size="20" fill="#6d645d">{escape(report.comparison.current.label)}</text>

  <rect x="620" y="244" width="254" height="154" rx="28" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="648" y="286" font-size="16" letter-spacing="2" fill="#6d645d">PREVIOUS COMPARE</text>
  <text x="648" y="348" font-size="48" font-weight="700" fill="#1f1a17">${report.comparison.previous.estimated_cost_usd:.2f}</text>
  <text x="648" y="378" font-size="20" fill="#6d645d">{escape(report.comparison.previous.label)}</text>

  <rect x="892" y="244" width="236" height="154" rx="28" fill="#115e59"/>
  <text x="920" y="286" font-size="16" letter-spacing="2" fill="#d7faf5">PROJECTED</text>
  <text x="920" y="348" font-size="44" font-weight="700" fill="#ffffff">${report.costs.projected_monthly_cost_usd:.2f}</text>
  <text x="920" y="378" font-size="20" fill="#d7faf5">Monthly run rate</text>

  <rect x="76" y="436" width="1052" height="112" rx="28" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="104" y="474" font-size="18" letter-spacing="2" fill="#6d645d">HIGHEST SESSION</text>
  <text x="104" y="522" font-size="38" font-weight="700" fill="#1f1a17">${report.costs.highest_session_cost_usd:.2f}</text>
  <text x="420" y="522" font-size="24" fill="#4b4036">Window delta ${report.comparison.cost_delta_usd:+.2f}  •  Savings ${report.insights.possible_savings_usd:.2f}</text>

  <text x="1128" y="580" text-anchor="end" font-size="18" fill="#6d645d">Generated by codex-stats</text>
</svg>"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{escape(title)} cost card">
  <rect width="1200" height="630" fill="#f7efe2"/>
  <rect x="40" y="36" width="1120" height="558" rx="32" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="76" y="92" font-size="18" letter-spacing="3" fill="#b45309">CODEX STATS</text>
  <text x="76" y="150" font-size="56" font-weight="700" fill="#1f1a17">Cost Snapshot</text>
  <text x="76" y="194" font-size="24" fill="#6d645d">{escape(title)}</text>

  <rect x="76" y="244" width="254" height="154" rx="28" fill="#b45309"/>
  <text x="104" y="286" font-size="16" letter-spacing="2" fill="#ffedd5">TODAY</text>
  <text x="104" y="348" font-size="48" font-weight="700" fill="#ffffff">${report.costs.today_cost_usd:.2f}</text>
  <text x="104" y="378" font-size="20" fill="#ffedd5">Current day estimate</text>

  <rect x="348" y="244" width="254" height="154" rx="28" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="376" y="286" font-size="16" letter-spacing="2" fill="#6d645d">WEEK</text>
  <text x="376" y="348" font-size="48" font-weight="700" fill="#1f1a17">${report.costs.week_cost_usd:.2f}</text>
  <text x="376" y="378" font-size="20" fill="#6d645d">Rolling weekly total</text>

  <rect x="620" y="244" width="254" height="154" rx="28" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="648" y="286" font-size="16" letter-spacing="2" fill="#6d645d">MONTH</text>
  <text x="648" y="348" font-size="48" font-weight="700" fill="#1f1a17">${report.costs.month_cost_usd:.2f}</text>
  <text x="648" y="378" font-size="20" fill="#6d645d">Rolling monthly total</text>

  <rect x="892" y="244" width="236" height="154" rx="28" fill="#115e59"/>
  <text x="920" y="286" font-size="16" letter-spacing="2" fill="#d7faf5">PROJECTED</text>
  <text x="920" y="348" font-size="44" font-weight="700" fill="#ffffff">${report.costs.projected_monthly_cost_usd:.2f}</text>
  <text x="920" y="378" font-size="20" fill="#d7faf5">Monthly run rate</text>

  <rect x="76" y="436" width="1052" height="112" rx="28" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="104" y="474" font-size="18" letter-spacing="2" fill="#6d645d">HIGHEST SESSION</text>
  <text x="104" y="522" font-size="38" font-weight="700" fill="#1f1a17">${report.costs.highest_session_cost_usd:.2f}</text>
  <text x="420" y="522" font-size="24" fill="#4b4036">Possible savings ${report.insights.possible_savings_usd:.2f}  •  Suggestion: {escape(report.insights.suggestion[:44])}</text>

  <text x="1128" y="580" text-anchor="end" font-size="18" fill="#6d645d">Generated by codex-stats</text>
</svg>"""


def _format_focus_card_svg(report: ReportData | DashboardWindow, title: str) -> str:
    anomalies = report.insights.anomalies[:3] or ["No active anomalies"]
    recommendations = report.insights.recommendations[:3] or ["Usage looks healthy."]
    anomaly_lines = _svg_bullet_list(anomalies, x=90, y=248, width=430, line_height=28, max_lines=8, fill="#8a4b0f")
    recommendation_lines = _svg_bullet_list(recommendations, x=620, y=248, width=460, line_height=28, max_lines=8, fill="#1f1a17")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{escape(title)} focus card">
  <rect width="1200" height="630" fill="#f2ece3"/>
  <rect x="40" y="36" width="1120" height="558" rx="32" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="76" y="92" font-size="18" letter-spacing="3" fill="#0f766e">CODEX STATS</text>
  <text x="76" y="150" font-size="56" font-weight="700" fill="#1f1a17">Focus Card</text>
  <text x="76" y="194" font-size="24" fill="#6d645d">{escape(title)}</text>

  <rect x="76" y="216" width="492" height="306" rx="28" fill="rgba(180,83,9,0.08)" stroke="rgba(180,83,9,0.18)"/>
  <text x="90" y="252" font-size="20" letter-spacing="2" fill="#8a4b0f">WHAT LOOKS OFF</text>
  {anomaly_lines}

  <rect x="604" y="216" width="524" height="306" rx="28" fill="rgba(15,118,110,0.08)" stroke="rgba(15,118,110,0.18)"/>
  <text x="620" y="252" font-size="20" letter-spacing="2" fill="#115e59">WHAT TO DO NEXT</text>
  {recommendation_lines}

  <rect x="76" y="540" width="1052" height="40" rx="20" fill="#fffaf2"/>
  <text x="602" y="566" text-anchor="middle" font-size="20" fill="#4b4036">Avg/request {report.summary.average_tokens_per_request:,.0f}  •  Cache ratio {escape(_fmt_percent(report.summary.cache_ratio))}  •  Large sessions {report.insights.large_session_count}</text>
</svg>"""


def _format_heatmap_card_svg(report: ReportData | DashboardWindow, title: str) -> str:
    chart_svg = _svg_heatmap_chart(report.activity_heatmap)
    subtitle = "Activity by weekday and hour. Darker cells indicate heavier local usage."
    return _wrap_chart_svg(f"{title} Heatmap", subtitle, chart_svg)


def _format_projects_card_svg(report: ReportData, title: str) -> str:
    project_rows = report.projects[:4]
    if not project_rows:
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{escape(title)} projects card">
  <rect width="1200" height="630" fill="#f5eee4"/>
  <rect x="40" y="36" width="1120" height="558" rx="32" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="76" y="92" font-size="18" letter-spacing="3" fill="#0f766e">CODEX STATS</text>
  <text x="76" y="150" font-size="56" font-weight="700" fill="#1f1a17">Project Snapshot</text>
  <text x="76" y="194" font-size="24" fill="#6d645d">{escape(title)}</text>
  <text x="76" y="320" font-size="30" fill="#4b4036">No project breakdown is available for this scoped report.</text>
</svg>"""
    max_tokens = max(entry.total_tokens for entry in project_rows) or 1
    rows = []
    for index, entry in enumerate(project_rows):
        y = 236 + index * 86
        width = 520 * (entry.total_tokens / max_tokens)
        rows.append(
            f'<text x="90" y="{y}" font-size="26" fill="#1f1a17">{escape(entry.name)}</text>'
            f'<rect x="90" y="{y + 18}" width="520" height="18" rx="9" fill="rgba(72,53,36,0.08)" />'
            f'<rect x="90" y="{y + 18}" width="{width:.1f}" height="18" rx="9" fill="#0f766e" />'
            f'<text x="636" y="{y + 34}" font-size="22" fill="#4b4036">{entry.total_tokens:,} tokens</text>'
            f'<text x="868" y="{y + 34}" font-size="22" fill="#4b4036">{entry.requests} req</text>'
            f'<text x="1014" y="{y + 34}" font-size="22" fill="#4b4036">${entry.estimated_cost_usd:.2f}</text>'
        )
    top_sessions = report.top_sessions[:2]
    session_lines = "".join(
        f'<text x="700" y="{260 + index * 42}" font-size="24" fill="#4b4036">• {escape(entry.project_name)} / {escape(entry.model or "unknown")}  {entry.total_tokens:,}</text>'
        for index, entry in enumerate(top_sessions)
    ) or '<text x="700" y="260" font-size="24" fill="#4b4036">No top sessions available.</text>'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="{escape(title)} projects card">
  <rect width="1200" height="630" fill="#f5eee4"/>
  <rect x="40" y="36" width="1120" height="558" rx="32" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="76" y="92" font-size="18" letter-spacing="3" fill="#0f766e">CODEX STATS</text>
  <text x="76" y="150" font-size="56" font-weight="700" fill="#1f1a17">Project Snapshot</text>
  <text x="76" y="194" font-size="24" fill="#6d645d">{escape(title)}</text>
  {''.join(rows)}
  <text x="700" y="224" font-size="20" letter-spacing="2" fill="#8a4b0f">TOP SESSIONS</text>
  {session_lines}
  <text x="1128" y="580" text-anchor="end" font-size="18" fill="#6d645d">Generated by codex-stats</text>
</svg>"""


def _wrap_chart_svg(title: str, subtitle: str, chart_svg: str) -> str:
    chart_body = chart_svg.strip()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720" role="img" aria-label="{escape(title)}">
  <rect width="1200" height="720" fill="#f6efe4"/>
  <rect x="40" y="36" width="1120" height="648" rx="30" fill="#fffaf2" stroke="rgba(66,48,31,0.10)"/>
  <text x="72" y="94" font-size="18" letter-spacing="3" fill="#0f766e">CODEX STATS</text>
  <text x="72" y="148" font-size="42" font-weight="700" fill="#1f1a17">{escape(title)}</text>
  <text x="72" y="184" font-size="22" fill="#6d645d">{escape(subtitle)}</text>
  <g transform="translate(72 220)">{chart_body}</g>
</svg>"""


def _svg_bullet_list(
    items: list[str],
    *,
    x: int,
    y: int,
    width: int,
    line_height: int,
    max_lines: int,
    fill: str,
) -> str:
    words_per_line = max(width // 13, 12)
    lines_used = 0
    rows: list[str] = []
    for item in items:
        wrapped = textwrap.wrap(item, width=words_per_line) or [item]
        for index, line in enumerate(wrapped):
            if lines_used >= max_lines:
                return "".join(rows)
            truncated = line
            if lines_used == max_lines - 1 and index < len(wrapped) - 1:
                truncated = line.rstrip(". ") + "..."
            current_y = y + lines_used * line_height
            text_x = x if index == 0 else x + 22
            prefix = "• " if index == 0 else ""
            rows.append(f'<text x="{text_x}" y="{current_y}" font-size="22" fill="{fill}">{escape(prefix + truncated)}</text>')
            lines_used += 1
        if lines_used >= max_lines:
            break
    return "".join(rows)


def format_watch_dashboard(
    summary: TimeSummary,
    compare: CompareReport,
    daily: list[DailyPoint],
    top: list[TopEntry],
    history: list[HistoryEntry],
    insights: InsightReport,
    alerts: list[WatchAlert],
    *,
    now: datetime | None = None,
    interval_seconds: float = 5.0,
    scope_label: str | None = None,
    options: FormatOptions | None = None,
) -> str:
    options = options or FormatOptions()
    current_time = now or datetime.now().astimezone()
    title = "Codex Stats Watch"
    if scope_label:
        title = f"{title} [{scope_label}]"
    lines = [
        title,
        f"Refreshed {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')} every {interval_seconds:g}s. Press Ctrl-C to stop.",
        "",
        format_summary(summary, options),
        "",
        format_compare(compare, options),
        "",
        format_watch_alerts(alerts, options),
        "",
        format_daily(daily, options),
        "",
        format_top(top, options),
        "",
        format_history(history, options),
        "",
        format_insights(insights, options),
    ]
    return "\n".join(lines)


def format_watch_alerts(alerts: list[WatchAlert], options: FormatOptions | None = None) -> str:
    options = options or FormatOptions()
    if not alerts:
        return _card("Alerts", [("Status", "No active alerts")], options)
    lines = [_box_top("Alerts", options)]
    for alert in alerts:
        severity = alert.severity.upper()
        if alert.severity == "critical":
            severity = _tint(severity, "31", options)
        elif alert.severity == "warning":
            severity = _tint(severity, "33", options)
        new_marker = _tint("NEW", "36", options) if alert.is_new else "   "
        lines.append(_box_line(f"{severity:<8} {new_marker:<3} {alert.name}"))
        wrapped = textwrap.wrap(alert.detail, width=41) or [""]
        for chunk in wrapped:
            lines.append(_box_line(f"         {chunk}"))
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


def _fmt_minutes(value: float) -> str:
    if value <= 0:
        return "0m"
    hours = int(value // 60)
    minutes = int(round(value % 60))
    if minutes == 60:
        hours += 1
        minutes = 0
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


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
