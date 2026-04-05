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
    DailyPoint,
    DoctorCheck,
    HistoryEntry,
    InsightReport,
    ImportSummary,
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
          <span class="hint">Largest session {report.summary.largest_session_tokens:,} tokens</span>
        </div>
        <div class="metric">
          <span class="label">Cache Ratio</span>
          <strong class="value">{escape(_fmt_percent(report.summary.cache_ratio))}</strong>
          <span class="hint">Possible savings ${report.insights.possible_savings_usd:.2f}</span>
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


def format_report_svg(report: ReportData, daily_points: list[DailyPoint] | None = None) -> str:
    title = f"Codex Stats {report.period.title()} Report"
    if report.project_name:
        title = f"{title}: {report.project_name}"
    daily_points = daily_points or []
    token_trend_svg = _svg_line_chart(
        [(point.day[5:], float(point.total_tokens)) for point in daily_points],
        stroke="#0f766e",
        fill="rgba(15, 118, 110, 0.14)",
        value_formatter=lambda value: f"{int(value):,}",
    )
    project_share_svg = _svg_bar_chart(
        [(entry.name, float(entry.total_tokens)) for entry in report.projects[:4]],
        bar_color="#b45309",
        value_formatter=lambda value: f"{int(value):,}",
        empty_label="No project breakdown for this scoped report.",
    )
    anomalies = report.insights.anomalies[:3] or ["No active anomalies"]
    recommendations = report.insights.recommendations[:3] or ["Usage looks healthy."]
    top_sessions = report.top_sessions[:3]
    top_sessions_text = "".join(
        f'<text x="64" y="{776 + index * 30}" font-size="18" fill="#1f1a17">{index + 1}. {escape(entry.project_name)} / {escape(entry.model or "unknown")}  {entry.total_tokens:,} tokens</text>'
        for index, entry in enumerate(top_sessions)
    ) or '<text x="64" y="776" font-size="18" fill="#1f1a17">No top sessions available.</text>'
    anomaly_badges = "".join(
        f'<rect x="{64 + index * 250}" y="846" width="220" height="44" rx="22" fill="rgba(180,83,9,0.12)" />'
        f'<text x="{174 + index * 250}" y="874" text-anchor="middle" font-size="16" fill="#8a4b0f">{escape(item)}</text>'
        for index, item in enumerate(anomalies)
    )
    recommendation_lines = "".join(
        f'<text x="64" y="{948 + index * 28}" font-size="18" fill="#4b4036">{escape(item)}</text>'
        for index, item in enumerate(recommendations)
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1200" viewBox="0 0 1200 1200" role="img" aria-label="{escape(title)}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#f9f3ea"/>
      <stop offset="100%" stop-color="#efe6d8"/>
    </linearGradient>
    <radialGradient id="glowA" cx="0%" cy="0%" r="90%">
      <stop offset="0%" stop-color="rgba(15,118,110,0.24)"/>
      <stop offset="100%" stop-color="rgba(15,118,110,0)"/>
    </radialGradient>
    <radialGradient id="glowB" cx="100%" cy="0%" r="90%">
      <stop offset="0%" stop-color="rgba(180,83,9,0.18)"/>
      <stop offset="100%" stop-color="rgba(180,83,9,0)"/>
    </radialGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="18" stdDeviation="22" flood-color="rgba(66,41,18,0.14)"/>
    </filter>
  </defs>
  <rect width="1200" height="1200" fill="url(#bg)"/>
  <rect width="1200" height="1200" fill="url(#glowA)"/>
  <rect width="1200" height="1200" fill="url(#glowB)"/>

  <rect x="38" y="34" width="1124" height="1132" rx="36" fill="rgba(255,250,241,0.88)" stroke="rgba(72,53,36,0.10)" filter="url(#shadow)"/>

  <text x="64" y="90" font-size="18" letter-spacing="3" fill="#0f766e">CODEX STATS</text>
  <text x="64" y="154" font-size="52" font-weight="700" fill="#1f1a17">{escape(title)}</text>
  <text x="64" y="194" font-size="22" fill="#6d645d">Standalone shareable report asset</text>
  <text x="64" y="240" font-size="22" fill="#4b4036">Top model: {escape(report.summary.top_model or "unknown")}  •  Trend: {escape("n/a" if report.comparison.total_tokens_delta_pct is None else f"{report.comparison.total_tokens_delta_pct:+.1f}%")}  •  Cache ratio: {escape(_fmt_percent(report.summary.cache_ratio))}</text>

  <rect x="64" y="282" width="240" height="128" rx="24" fill="#fffaf1" stroke="rgba(72,53,36,0.10)"/>
  <text x="88" y="320" font-size="16" letter-spacing="2" fill="#6d645d">TOKENS</text>
  <text x="88" y="372" font-size="44" font-weight="700" fill="#1f1a17">{report.summary.total_tokens:,}</text>
  <text x="88" y="398" font-size="18" fill="#6d645d">{report.summary.requests} requests</text>

  <rect x="320" y="282" width="240" height="128" rx="24" fill="#fffaf1" stroke="rgba(72,53,36,0.10)"/>
  <text x="344" y="320" font-size="16" letter-spacing="2" fill="#6d645d">EST. COST</text>
  <text x="344" y="372" font-size="44" font-weight="700" fill="#1f1a17">${report.summary.estimated_cost_usd:.2f}</text>
  <text x="344" y="398" font-size="18" fill="#6d645d">Projected ${report.costs.projected_monthly_cost_usd:.2f}</text>

  <rect x="576" y="282" width="240" height="128" rx="24" fill="#fffaf1" stroke="rgba(72,53,36,0.10)"/>
  <text x="600" y="320" font-size="16" letter-spacing="2" fill="#6d645d">AVG / REQUEST</text>
  <text x="600" y="372" font-size="44" font-weight="700" fill="#1f1a17">{report.summary.average_tokens_per_request:,.0f}</text>
  <text x="600" y="398" font-size="18" fill="#6d645d">Largest {report.summary.largest_session_tokens:,}</text>

  <rect x="832" y="282" width="304" height="128" rx="24" fill="#0f766e" opacity="0.96"/>
  <text x="856" y="320" font-size="16" letter-spacing="2" fill="#d8f3ef">RECOMMENDATION</text>
  <text x="856" y="360" font-size="24" font-weight="700" fill="#ffffff">{escape(report.insights.suggestion[:34])}</text>
  <text x="856" y="390" font-size="18" fill="#d8f3ef">{escape(report.insights.suggestion[34:68])}</text>

  <rect x="64" y="442" width="520" height="310" rx="28" fill="#fffaf1" stroke="rgba(72,53,36,0.10)"/>
  <text x="88" y="480" font-size="24" font-weight="700" fill="#1f1a17">Daily Token Trend</text>
  <g transform="translate(0 10)">{token_trend_svg}</g>

  <rect x="616" y="442" width="520" height="310" rx="28" fill="#fffaf1" stroke="rgba(72,53,36,0.10)"/>
  <text x="640" y="480" font-size="24" font-weight="700" fill="#1f1a17">Project Share</text>
  <g transform="translate(0 28)">{project_share_svg}</g>

  <rect x="64" y="782" width="1072" height="110" rx="28" fill="#fffaf1" stroke="rgba(72,53,36,0.10)"/>
  <text x="88" y="820" font-size="24" font-weight="700" fill="#1f1a17">Top Sessions</text>
  {top_sessions_text}

  <text x="64" y="930" font-size="24" font-weight="700" fill="#1f1a17">Anomalies</text>
  {anomaly_badges}

  <text x="64" y="1036" font-size="24" font-weight="700" fill="#1f1a17">Recommended Actions</text>
  {recommendation_lines}

  <text x="1136" y="1134" text-anchor="end" font-size="18" fill="#6d645d">Generated by codex-stats</text>
</svg>
"""


def _svg_line_chart(
    points: list[tuple[str, float]],
    *,
    stroke: str,
    fill: str,
    value_formatter,
) -> str:
    if not points:
        return '<div class="chart-empty">No data available.</div>'
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
        f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Trend chart">'
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
        return f'<div class="chart-empty">{escape(empty_label)}</div>'
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
    return f'<svg class="chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Bar chart">{"".join(rows)}</svg>'


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
