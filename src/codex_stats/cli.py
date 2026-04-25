from __future__ import annotations

import argparse
import tempfile
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

from .config import Paths, PricingConfig, load_pricing_config
from .display import format_dashboard_html
from .metrics import (
    local_date,
    summarize_activity_heatmap_from_details,
    summarize_badges,
    summarize_compare_from_details,
    summarize_costs_from_details,
    summarize_daily_from_details,
    summarize_details,
    summarize_expensive_session,
    summarize_history_from_details,
    summarize_insights_from_details,
    summarize_project_drilldowns_from_details,
    summarize_projects_from_details,
    summarize_takeaways,
    summarize_top_sessions_from_details,
    summarize_work_rhythm,
)
from .ingest import iter_session_details
from .models import DashboardData, DashboardWindow, SessionDetails
from .transfer import write_export


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-stats",
        description="Open a local Codex usage dashboard in the browser or export normalized stats.",
    )
    parser.add_argument(
        "--output",
        dest="dashboard_output",
        help="Write dashboard HTML to a file instead of a temp file.",
    )
    parser.add_argument("--no-open", action="store_true", help="Write the dashboard without opening the browser.")
    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser("export", help="Export normalized local stats to JSON.")
    export_parser.add_argument("output", help="Output JSON file.")
    export_parser.add_argument("--since", help="Only export the last Nd of sessions, for example 30d.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = Paths.discover()

    if args.command == "export":
        output_path = write_export(paths, Path(args.output).expanduser(), since=args.since)
        print(f"Exported stats to {output_path}")
        return 0

    if args.command is not None:
        parser.print_help()
        return 1

    dashboard = _build_dashboard(paths)
    output_path = _write_dashboard_output(format_dashboard_html(dashboard), args.dashboard_output)
    print(f"Wrote dashboard to {output_path}")
    if not args.no_open:
        _open_report_in_browser(output_path)
        print(f"Opened dashboard in browser: {output_path}")
    return 0


def _build_dashboard(paths: Paths, now: datetime | None = None) -> DashboardData:
    current_time = now or datetime.now().astimezone()
    pricing = load_pricing_config(paths)
    all_details = iter_session_details(paths)

    today_details = _details_for_last_days(all_details, 1, current_time)
    week_details = _details_for_last_days(all_details, 7, current_time)
    month_details = _details_for_last_days(all_details, 30, current_time)

    windows = [
        _build_window(
            key="day",
            label="Day",
            description="Today’s usage with a direct comparison to yesterday.",
            current_details=today_details,
            previous_details=_details_for_previous_window(all_details, 1, current_time),
            current_label="today",
            previous_label="yesterday",
            trend_days=1,
            all_details=all_details,
            pricing=pricing,
            now=current_time,
        ),
        _build_window(
            key="week",
            label="Week",
            description="Rolling 7-day totals, recent trend, and the busiest sessions this week.",
            current_details=week_details,
            previous_details=_details_for_previous_window(all_details, 7, current_time),
            current_label="last 7 days",
            previous_label="previous 7 days",
            trend_days=7,
            all_details=all_details,
            pricing=pricing,
            now=current_time,
        ),
        _build_window(
            key="month",
            label="Month",
            description="Rolling 30-day totals with project concentration and cost pressure.",
            current_details=month_details,
            previous_details=_details_for_previous_window(all_details, 30, current_time),
            current_label="last 30 days",
            previous_label="previous 30 days",
            trend_days=30,
            all_details=all_details,
            pricing=pricing,
            now=current_time,
        ),
        _build_all_time_window(
            all_details=all_details,
            pricing=pricing,
            now=current_time,
        ),
    ]
    return DashboardData(generated_at=current_time, windows=windows)


def _build_window(
    *,
    key: str,
    label: str,
    description: str,
    current_details: list[SessionDetails],
    previous_details: list[SessionDetails],
    current_label: str,
    previous_label: str,
    trend_days: int,
    all_details: list[SessionDetails],
    pricing: PricingConfig,
    now: datetime,
) -> DashboardWindow:
    summary = summarize_details(current_label, current_details, pricing)
    comparison = summarize_compare_from_details(
        current_details,
        previous_details,
        current_label=current_label,
        previous_label=previous_label,
        pricing=pricing,
    )
    insights = summarize_insights_from_details(current_details, pricing=pricing, month=summary, now=now)
    costs = summarize_costs_from_details(
        current_details,
        pricing=pricing,
        today=summary,
        week=summary,
        month=summary,
        now=now,
    )
    history_source = current_details if current_details else all_details
    daily_points = summarize_daily_from_details(current_details, days=max(trend_days, 1), now=now, pricing=pricing)
    activity_heatmap = summarize_activity_heatmap_from_details(current_details, timezone=now.tzinfo)
    return DashboardWindow(
        key=key,
        label=label,
        description=description,
        comparison_label=f"{current_label} vs {previous_label}",
        summary=summary,
        comparison=comparison,
        projects=summarize_projects_from_details(current_details, pricing)[:10],
        top_sessions=summarize_top_sessions_from_details(current_details, pricing, limit=10),
        history=summarize_history_from_details(history_source, pricing, limit=10),
        daily_points=daily_points,
        costs=costs,
        insights=insights,
        activity_heatmap=activity_heatmap,
        takeaways=summarize_takeaways(summary=summary, comparison=comparison, costs=costs, insights=insights),
        badges=summarize_badges(summary=summary, daily_points=daily_points, activity_heatmap=activity_heatmap),
        expensive_session=summarize_expensive_session(current_details, pricing),
        work_rhythm=summarize_work_rhythm(daily_points, activity_heatmap),
        project_drilldowns=summarize_project_drilldowns_from_details(
            current_details,
            days=max(trend_days, 1),
            now=now,
            pricing=pricing,
            limit=5,
        ),
    )


def _build_all_time_window(
    *,
    all_details: list[SessionDetails],
    pricing: PricingConfig,
    now: datetime,
) -> DashboardWindow:
    summary = summarize_details("all time", all_details, pricing)
    recent_details = _details_for_last_days(all_details, 30, now)
    previous_details = _details_for_previous_window(all_details, 30, now)
    comparison = summarize_compare_from_details(
        recent_details,
        previous_details,
        current_label="recent 30 days",
        previous_label="prior 30 days",
        pricing=pricing,
    )
    costs = summarize_costs_from_details(all_details, pricing=pricing, now=now)
    insights = summarize_insights_from_details(all_details, pricing=pricing, month=summary, now=now)
    trend_days = _all_time_trend_days(all_details, now)
    trend_details = _details_for_last_days(all_details, trend_days, now)
    daily_points = summarize_daily_from_details(trend_details, days=trend_days, now=now, pricing=pricing)
    activity_heatmap = summarize_activity_heatmap_from_details(all_details, timezone=now.tzinfo)
    return DashboardWindow(
        key="all",
        label="All Time",
        description=f"All recorded sessions. Trend charts cover the last {trend_days} days so the page stays readable.",
        comparison_label="recent 30 days vs prior 30 days",
        summary=summary,
        comparison=comparison,
        projects=summarize_projects_from_details(all_details, pricing)[:10],
        top_sessions=summarize_top_sessions_from_details(all_details, pricing, limit=10),
        history=summarize_history_from_details(all_details, pricing, limit=10),
        daily_points=daily_points,
        costs=costs,
        insights=insights,
        activity_heatmap=activity_heatmap,
        takeaways=summarize_takeaways(
            summary=summary,
            comparison=comparison,
            costs=costs,
            insights=insights,
        ),
        badges=summarize_badges(summary=summary, daily_points=daily_points, activity_heatmap=activity_heatmap),
        expensive_session=summarize_expensive_session(all_details, pricing),
        work_rhythm=summarize_work_rhythm(daily_points, activity_heatmap),
        project_drilldowns=summarize_project_drilldowns_from_details(
            all_details,
            days=trend_days,
            now=now,
            pricing=pricing,
            limit=5,
        ),
    )


def _details_for_last_days(details: list[SessionDetails], days: int, now: datetime) -> list[SessionDetails]:
    safe_days = max(days, 1)
    end_day = now.date()
    start_day = end_day - timedelta(days=safe_days - 1)
    return _filter_details_between(details, start_day, end_day, now)


def _details_for_previous_window(details: list[SessionDetails], days: int, now: datetime) -> list[SessionDetails]:
    safe_days = max(days, 1)
    end_day = now.date() - timedelta(days=safe_days)
    start_day = end_day - timedelta(days=safe_days - 1)
    return _filter_details_between(details, start_day, end_day, now)


def _filter_details_between(
    details: list[SessionDetails],
    start_day,
    end_day,
    now: datetime,
) -> list[SessionDetails]:
    return [
        detail
        for detail in details
        if start_day <= local_date(detail.session.created_at, now.tzinfo) <= end_day
    ]


def _all_time_trend_days(details: list[SessionDetails], now: datetime) -> int:
    if not details:
        return 30
    newest_day = max(local_date(detail.session.created_at, now.tzinfo) for detail in details)
    oldest_day = min(local_date(detail.session.created_at, now.tzinfo) for detail in details)
    span_days = (newest_day - oldest_day).days + 1
    return min(max(span_days, 1), 90)


def _write_dashboard_output(content: str, output: str | None) -> Path:
    if output:
        output_path = Path(output).expanduser()
    else:
        handle = tempfile.NamedTemporaryFile(prefix="codex-stats-dashboard-", suffix=".html", delete=False)
        handle.close()
        output_path = Path(handle.name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8")
    return output_path


def _open_report_in_browser(path: Path) -> None:
    webbrowser.open(path.resolve().as_uri())


if __name__ == "__main__":
    raise SystemExit(main())
