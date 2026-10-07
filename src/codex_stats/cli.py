from __future__ import annotations

import argparse
import os
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

from .config import BudgetConfig, ConfigError, Paths, PricingConfig, load_budget_config, load_pricing_config
from .display import format_dashboard_html
from .ingest import ENV_MAX_SESSIONS
from .leaderboard import (
    DEFAULT_IDLE_TIMEOUT_SECONDS,
    ENV_IDLE_TIMEOUT,
    LeaderboardConfig,
    LeaderboardSubmitServer,
)
from .metrics import (
    DEFAULT_IDLE_BRANCH_DAYS,
    local_date,
    summarize_activity_heatmap_from_details,
    summarize_badges,
    summarize_behavior_from_details,
    summarize_branches_from_details,
    summarize_compare_from_details,
    summarize_costs_from_details,
    summarize_daily_from_details,
    summarize_details,
    summarize_efficiency_from_details,
    estimate_detail_cost,
    summarize_expensive_session,
    summarize_files_from_details,
    summarize_history_from_details,
    summarize_insights_from_details,
    summarize_project_drilldowns_from_details,
    summarize_projects_from_details,
    summarize_providers_from_details,
    summarize_source_breakdown_from_details,
    summarize_source_daily_from_details,
    summarize_takeaways,
    summarize_top_sessions_from_details,
    summarize_tool_efficiency_from_details,
    summarize_work_rhythm,
)
from .models import (
    DashboardData,
    DashboardScope,
    DashboardWindow,
    SessionDetails,
)
from .sources import Source, iter_sources


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="codex-stats",
        description="Open a local coding-agent usage dashboard in the browser.",
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    paths = Paths.discover()

    dashboard = _build_dashboard(paths)
    submit_server = _start_leaderboard(dashboard)
    output_path = _write_dashboard_output(
        format_dashboard_html(dashboard, leaderboard=_leaderboard_preview(submit_server)),
        paths.dashboard_file,
    )
    print(f"Wrote dashboard to {output_path}")
    _open_report_in_browser(output_path)
    print(f"Opened dashboard in browser: {output_path}")
    return _run_submit_endpoint(submit_server)


def _run_submit_endpoint(server: LeaderboardSubmitServer | None) -> int:
    """Keep the dashboard submittable, then hand the shell back.

    The Submit button posts to a loopback endpoint, and the only copy of the page
    that can post lives in the browser, so the endpoint cannot be closed the moment
    the dashboard opens. It is detached into its own process so this command still
    returns immediately, and that process stops on its own once nobody submits.
    """
    if server is None:
        return 0
    timeout = _idle_timeout_seconds()
    try:
        detached = server.detach(timeout)
    except OSError:
        detached = False
        server.start()
    if not detached:
        # No fork on this platform, so this process owns the endpoint and has to
        # stay alive to serve it. Say so rather than appearing to hang.
        minutes = max(round(timeout / 60.0), 1)
        print(
            f"Leaderboard enabled: Submit to Leaderboard stays available for {minutes} "
            f"minute{'s' if minutes != 1 else ''}. Press Ctrl+C to stop it now."
        )
        try:
            server.serve_until_idle(timeout)
        except KeyboardInterrupt:
            print("\nLeaderboard submit endpoint stopped.")
        finally:
            server.close()
        return 0
    print(
        f"Leaderboard enabled: Submit to Leaderboard stays available for "
        f"{_duration_label(timeout)}. This command has returned; the endpoint stops on its own."
    )
    return 0


def _duration_label(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)} second{'s' if seconds != 1 else ''}"
    minutes = seconds / 60.0
    rounded = round(minutes)
    if rounded == 1:
        return "1 minute"
    return f"{rounded} minutes" if abs(minutes - rounded) < 0.5 else f"{minutes:.1f} minutes"


def _start_leaderboard(dashboard: DashboardData) -> LeaderboardSubmitServer | None:
    """Bind the loopback submit endpoint when the leaderboard is configured.

    Binding, rather than serving, happens here: the generated HTML has to carry a
    URL that is already live, and the port is only known once the socket exists.
    Nothing accepts connections until ``detach`` hands the socket off.
    """
    config = LeaderboardConfig.from_env()
    if config is None:
        return None
    server = LeaderboardSubmitServer(config, dashboard)
    server.bind()
    return server


def _leaderboard_preview(server: LeaderboardSubmitServer | None) -> dict[str, object] | None:
    if server is None:
        return None
    return server.preview()


def _idle_timeout_seconds() -> float:
    """How long the detached submit endpoint waits for a submission before exiting.

    The dashboard is a file the browser already holds, so the endpoint that page
    talks to has to outlive the run that wrote it. Bounding that wait is what stops
    every invocation from leaving a process behind: without a deadline the command
    never returns, and a tool you run from a shell has to give the shell back.
    """
    raw = os.environ.get(ENV_IDLE_TIMEOUT, "").strip()
    if not raw:
        return DEFAULT_IDLE_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        return DEFAULT_IDLE_TIMEOUT_SECONDS
    return max(seconds, 0.0)


def _build_dashboard(paths: Paths, now: datetime | None = None) -> DashboardData:
    current_time = now or datetime.now().astimezone()
    pricing, config_error = _load_pricing_or_default(paths)
    budget, budget_error = _load_budget_or_default(paths)
    if config_error is None and budget_error is not None:
        config_error = budget_error
    selected_sources = iter_sources(paths)
    source_details = {source.key: source.ingest() for source in selected_sources}
    all_details = [detail for source in selected_sources for detail in source_details[source.key]]

    overview = _build_scope(
        key="overview",
        label="Overview",
        description="Every tool combined. Start here to see total activity, spend, and where the work happened.",
        source="all",
        details=all_details,
        pricing=pricing,
        now=current_time,
        build_tool_breakdown=True,
    )
    tool_scopes = [
        _build_scope(
            key=source.key,
            label=source.label,
            description=source.description,
            source=source.key,
            details=source_details[source.key],
            pricing=pricing,
            now=current_time,
        )
        for source in selected_sources
    ]
    return DashboardData(
        generated_at=current_time,
        scopes=[overview, *tool_scopes],
        coverage_note=_coverage_note(selected_sources),
        config_error=config_error,
        budget_note=_budget_note(budget, pricing, all_details, current_time),
    )


def _load_budget_or_default(paths: Paths) -> tuple[BudgetConfig, str | None]:
    """Read the optional monthly budget, or the unlimited default.

    A malformed ``[budget]`` block is surfaced through the same config_error banner
    as a bad pricing table: same file, same class of hand-edited mistake, same one-
    line answer instead of a traceback.
    """
    try:
        return load_budget_config(paths), None
    except ConfigError as error:
        return BudgetConfig(), f"{error.path}: {error.detail}"


def _budget_note(
    budget: BudgetConfig,
    pricing: PricingConfig,
    details: list[SessionDetails],
    current_time: datetime,
) -> str | None:
    """Compare the calendar-month spend to the user's limit, if any.

    The budget is measured against the calendar month, not the rolling 30-day tab:
    a budget is a per-month commitment in someone's calendar terms, and the page
    already shows the rolling figure elsewhere. The banner appears at the warn
    ratio and turns into an over-limit statement once the limit passes.
    """
    if budget.monthly_limit_usd is None:
        return None
    month_start = current_time.date().replace(day=1)
    spent = sum(
        estimate_detail_cost(detail, pricing)
        for detail in details
        if month_start <= local_date(detail.session.created_at, current_time.tzinfo) <= current_time.date()
    )
    limit = budget.monthly_limit_usd
    ratio = spent / limit
    if ratio < budget.warn_at_ratio:
        return None
    if ratio >= 1.0:
        return (
            f"Over the ${limit:,.2f} monthly budget: ${spent:,.2f} spent this calendar month "
            f"({ratio:.0%} of limit)."
        )
    return (
        f"Approaching the ${limit:,.2f} monthly budget: ${spent:,.2f} spent this calendar month "
        f"({ratio:.0%} of limit)."
    )


def _load_pricing_or_default(paths: Paths) -> tuple[PricingConfig, str | None]:
    """Read the rate table, degrading to the built-in one on a bad config file.

    The dashboard is still worth rendering with stock rates: a user with a typo in
    one override can see everything except their own custom prices, and is told on
    the page which file was ignored. Raising instead would make a one-character
    mistake cost the entire report.
    """
    try:
        return load_pricing_config(paths), None
    except ConfigError as error:
        return PricingConfig(), f"{error.path}: {error.detail}"


def _coverage_note(sources: list[Source]) -> str | None:
    """Admit to a bounded history read, or stay quiet when nothing was dropped.

    Every source that can drop history reports it here, because a window that
    silently shows a partial history is worse than one that says it is partial.
    Sources are named individually so a reader can tell which of their tools was
    truncated instead of inferring it from a single blended total. The source
    objects come from the ingest pass rather than being rebuilt here, so the
    availability flags and paths are looked up once per run.
    """
    dropped_by_source: list[str] = []
    total_analyzed = 0
    total_on_disk = 0
    for source in sources:
        if not source.available:
            continue
        try:
            analyzed, total = source.coverage()
        except Exception:
            # Coverage is disclosure. A source that cannot be counted must not stop
            # the dashboard, and claiming a complete history would be a lie, so the
            # source stays silent rather than asserting either way.
            continue
        if not total or analyzed >= total:
            continue
        dropped_by_source.append(f"{source.label} kept {analyzed:,} of {total:,}")
        total_analyzed += analyzed
        total_on_disk += total
    if not dropped_by_source:
        return None
    dropped = total_on_disk - total_analyzed
    listed = "; ".join(dropped_by_source)
    return (
        f"Showing the most recent {total_analyzed:,} of {total_on_disk:,} sessions "
        f"across your tools ({listed}). "
        f"{dropped:,} older session{'s' if dropped != 1 else ''} "
        f"{'are' if dropped != 1 else 'is'} excluded from every total and chart, so All Time is a "
        f"recent-history total rather than a lifetime one. "
        f"Set {ENV_MAX_SESSIONS}=0 to read everything, which takes longer."
    )


def _build_scope(
    *,
    key: str,
    label: str,
    description: str,
    source: str,
    details: list[SessionDetails],
    pricing: PricingConfig,
    now: datetime,
    build_tool_breakdown: bool = False,
) -> DashboardScope:
    today_details = _details_for_last_days(details, 1, now)
    week_details = _details_for_last_days(details, 7, now)
    month_details = _details_for_last_days(details, 30, now)
    windows = [
        _build_window(
            key="day",
            label="Day",
            description="Today’s usage with a direct comparison to yesterday.",
            current_details=today_details,
            previous_details=_details_for_previous_window(details, 1, now),
            current_label="today",
            previous_label="yesterday",
            trend_days=1,
            all_details=details,
            pricing=pricing,
            now=now,
            build_tool_breakdown=build_tool_breakdown,
        ),
        _build_window(
            key="week",
            label="Week",
            description="Rolling 7-day totals, recent trend, and the busiest sessions this week.",
            current_details=week_details,
            previous_details=_details_for_previous_window(details, 7, now),
            current_label="last 7 days",
            previous_label="previous 7 days",
            trend_days=7,
            all_details=details,
            pricing=pricing,
            now=now,
            build_tool_breakdown=build_tool_breakdown,
        ),
        _build_window(
            key="month",
            label="Month",
            description="Rolling 30-day totals with project concentration and cost pressure.",
            current_details=month_details,
            previous_details=_details_for_previous_window(details, 30, now),
            current_label="last 30 days",
            previous_label="previous 30 days",
            trend_days=30,
            all_details=details,
            pricing=pricing,
            now=now,
            build_tool_breakdown=build_tool_breakdown,
        ),
        _build_all_time_window(
            all_details=details,
            pricing=pricing,
            now=now,
            build_tool_breakdown=build_tool_breakdown,
        ),
    ]
    return DashboardScope(
        key=key,
        label=label,
        description=description,
        source=source,
        windows=windows,
    )


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
    build_tool_breakdown: bool = False,
) -> DashboardWindow:
    summary = summarize_details(current_label, current_details, pricing, timezone=now.tzinfo)
    comparison = summarize_compare_from_details(
        current_details,
        previous_details,
        current_label=current_label,
        previous_label=previous_label,
        pricing=pricing,
        current_summary=summary,
        timezone=now.tzinfo,
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
    file_impact = summarize_files_from_details(current_details, limit=10)
    behavior = summarize_behavior_from_details(current_details)
    efficiency = summarize_efficiency_from_details(current_details, pricing=pricing)
    branches = summarize_branches_from_details(
        current_details,
        pricing=pricing,
        now=now,
        idle_days=DEFAULT_IDLE_BRANCH_DAYS,
    )
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
        takeaways=summarize_takeaways(
            summary=summary,
            comparison=comparison,
            costs=costs,
            insights=insights,
            file_impact=file_impact,
            behavior=behavior,
            branches=branches,
            efficiency=efficiency,
        ),
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
        file_impact=file_impact,
        behavior=behavior,
        branches=branches,
        providers=summarize_providers_from_details(current_details, pricing),
        efficiency=efficiency,
        tool_efficiency=(
            summarize_tool_efficiency_from_details(current_details, pricing=pricing)
            if build_tool_breakdown
            else []
        ),
        tool_breakdown=(
            summarize_source_breakdown_from_details(current_details, pricing)
            if build_tool_breakdown
            else None
        ),
        tool_daily_points=(
            summarize_source_daily_from_details(
                current_details,
                days=max(trend_days, 1),
                now=now,
                pricing=pricing,
            )
            if build_tool_breakdown
            else None
        ),
    )


def _build_all_time_window(
    *,
    all_details: list[SessionDetails],
    pricing: PricingConfig,
    now: datetime,
    build_tool_breakdown: bool = False,
) -> DashboardWindow:
    summary = summarize_details("all time", all_details, pricing, timezone=now.tzinfo)
    recent_details = _details_for_last_days(all_details, 30, now)
    previous_details = _details_for_previous_window(all_details, 30, now)
    comparison = summarize_compare_from_details(
        recent_details,
        previous_details,
        current_label="recent 30 days",
        previous_label="prior 30 days",
        pricing=pricing,
        timezone=now.tzinfo,
    )
    costs = summarize_costs_from_details(all_details, pricing=pricing, now=now)
    insights = summarize_insights_from_details(all_details, pricing=pricing, month=summary, now=now)
    trend_days = _all_time_trend_days(all_details, now)
    trend_details = _details_for_last_days(all_details, trend_days, now)
    daily_points = summarize_daily_from_details(trend_details, days=trend_days, now=now, pricing=pricing)
    activity_heatmap = summarize_activity_heatmap_from_details(all_details, timezone=now.tzinfo)
    file_impact = summarize_files_from_details(all_details, limit=10)
    behavior = summarize_behavior_from_details(all_details)
    efficiency = summarize_efficiency_from_details(all_details, pricing=pricing)
    branches = summarize_branches_from_details(
        all_details,
        pricing=pricing,
        now=now,
        idle_days=DEFAULT_IDLE_BRANCH_DAYS,
    )
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
            file_impact=file_impact,
            behavior=behavior,
            branches=branches,
            efficiency=efficiency,
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
        file_impact=file_impact,
        behavior=behavior,
        branches=branches,
        providers=summarize_providers_from_details(all_details, pricing),
        efficiency=efficiency,
        tool_efficiency=(
            summarize_tool_efficiency_from_details(all_details, pricing=pricing)
            if build_tool_breakdown
            else []
        ),
        tool_breakdown=(
            summarize_source_breakdown_from_details(all_details, pricing)
            if build_tool_breakdown
            else None
        ),
        tool_daily_points=(
            summarize_source_daily_from_details(
                all_details,
                days=trend_days,
                now=now,
                pricing=pricing,
            )
            if build_tool_breakdown
            else None
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


def _write_dashboard_output(content: str, output_path: Path | None = None) -> Path:
    """Write the dashboard to a stable path so it can be reopened and refreshed.

    Overwriting in place is what makes a refresh work: the browser tab keeps the
    same URL, and browsers re-read the file on reload rather than serving the
    cached copy that a new random filename would have avoided.
    """
    target = output_path or Paths.discover().dashboard_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content + ("" if content.endswith("\n") else "\n"), encoding="utf-8")
    return target


def _open_report_in_browser(path: Path) -> None:
    """Open the dashboard, defeating the browser's copy of a previous run.

    Now that the path is stable, a plain ``file://`` open can be served straight
    from the browser cache, which would show last run's numbers. The file's mtime
    rides along as a query string so a changed file always means a changed URL,
    while an unchanged file still opens the tab that is already there.
    """
    uri = path.resolve().as_uri()
    try:
        version = path.stat().st_mtime_ns
    except OSError:
        version = 0
    webbrowser.open(f"{uri}?v={version}")


if __name__ == "__main__":
    raise SystemExit(main())
