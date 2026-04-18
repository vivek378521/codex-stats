from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, tzinfo
import re
from statistics import median

from .config import Paths, PricingConfig, load_config, load_pricing_config
from .ingest import get_session_details, iter_session_details
from .models import (
    BreakdownEntry,
    CompareReport,
    CostSummary,
    DailyPoint,
    DoctorCheck,
    HeatmapCell,
    HistoryEntry,
    InsightReport,
    SessionDetails,
    TimeSummary,
    TopEntry,
    ReportData,
    WatchAlert,
)

def estimate_cost_usd(total_tokens: int, usd_per_1k_tokens: float) -> float:
    return round((total_tokens / 1000.0) * usd_per_1k_tokens, 4)


def estimate_detail_cost(detail: SessionDetails, pricing: PricingConfig) -> float:
    return estimate_cost_usd(detail.effective_total_tokens(), pricing.rate_for_model(detail.session.model))


def summarize_today(paths: Paths, now: datetime | None = None) -> TimeSummary:
    current_time = now or datetime.now().astimezone()
    return summarize_period(paths, "today", current_time.date(), current_time.date(), current_time.tzinfo)


def summarize_week(paths: Paths, now: datetime | None = None) -> TimeSummary:
    current_time = now or datetime.now().astimezone()
    end_day = current_time.date()
    start_day = end_day - timedelta(days=6)
    return summarize_period(paths, "week", start_day, end_day, current_time.tzinfo)


def summarize_month(paths: Paths, now: datetime | None = None) -> TimeSummary:
    current_time = now or datetime.now().astimezone()
    end_day = current_time.date()
    start_day = end_day - timedelta(days=29)
    return summarize_period(paths, "month", start_day, end_day, current_time.tzinfo)


def summarize_last_days(paths: Paths, days: int, now: datetime | None = None) -> TimeSummary:
    details = details_for_last_days(paths, days, now=now)
    safe_days = max(days, 1)
    return summarize_details(f"last {safe_days} days", details)


def details_for_last_days(paths: Paths, days: int, now: datetime | None = None) -> list[SessionDetails]:
    current_time = now or datetime.now().astimezone()
    safe_days = max(days, 1)
    end_day = current_time.date()
    start_day = end_day - timedelta(days=safe_days - 1)
    return [
        detail
        for detail in iter_session_details(paths)
        if start_day <= local_date(detail.session.created_at, current_time.tzinfo) <= end_day
    ]


def filter_details_by_project(details: list[SessionDetails], project_name: str | None) -> list[SessionDetails]:
    if not project_name:
        return details
    lowered = project_name.lower()
    return [detail for detail in details if detail.session.project_name.lower() == lowered]


def parse_since_days(value: str) -> int:
    match = re.fullmatch(r"(\d+)d", value.strip().lower())
    if not match:
        raise ValueError("Expected --since in the form Nd, for example 30d")
    return int(match.group(1))


def summarize_period(
    paths: Paths,
    label: str,
    start_day: date,
    end_day: date,
    timezone: tzinfo | None,
) -> TimeSummary:
    details = [
        detail
        for detail in iter_session_details(paths)
        if start_day <= local_date(detail.session.created_at, timezone) <= end_day
    ]
    pricing = load_pricing_config(paths)
    return summarize_details(label, details, pricing)


def summarize_details(label: str, details: list[SessionDetails], pricing: PricingConfig | None = None) -> TimeSummary:
    pricing = pricing or PricingConfig()
    sessions_count = len(details)
    requests = sum(detail.request_count for detail in details)
    input_tokens = sum(detail.input_tokens or 0 for detail in details)
    output_tokens = sum(detail.output_tokens or 0 for detail in details)
    cached_input_tokens = sum(detail.cached_input_tokens or 0 for detail in details)
    reasoning_output_tokens = sum(detail.reasoning_output_tokens or 0 for detail in details)
    total_tokens = sum(detail.effective_total_tokens() for detail in details)
    model_counter = Counter(detail.session.model for detail in details if detail.session.model)
    top_model = model_counter.most_common(1)[0][0] if model_counter else None
    average_tokens_per_request = total_tokens / requests if requests else 0.0
    cache_ratio = (cached_input_tokens / input_tokens) if input_tokens else None
    largest_session_tokens = max((detail.effective_total_tokens() for detail in details), default=0)
    requests_per_session = requests / sessions_count if sessions_count else 0.0
    session_totals = [detail.effective_total_tokens() for detail in details]
    session_requests = [detail.request_count for detail in details]
    session_durations = [detail.duration_minutes() for detail in details]
    total_duration_minutes = sum(session_durations)
    return TimeSummary(
        label=label,
        sessions=sessions_count,
        requests=requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        reasoning_output_tokens=reasoning_output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=round(sum(estimate_detail_cost(detail, pricing) for detail in details), 4),
        top_model=top_model,
        average_tokens_per_request=average_tokens_per_request,
        cache_ratio=cache_ratio,
        largest_session_tokens=largest_session_tokens,
        requests_per_session=requests_per_session,
        median_tokens_per_session=float(median(session_totals)) if session_totals else 0.0,
        median_requests_per_session=float(median(session_requests)) if session_requests else 0.0,
        average_session_duration_minutes=(total_duration_minutes / sessions_count) if sessions_count else 0.0,
        median_session_duration_minutes=float(median(session_durations)) if session_durations else 0.0,
        tokens_per_minute=(total_tokens / total_duration_minutes) if total_duration_minutes > 0 else 0.0,
        project_concentration_top1_pct=_project_concentration(details, top_n=1),
        project_concentration_top3_pct=_project_concentration(details, top_n=3),
        longest_active_streak_days=_longest_active_streak_days(details),
        model_switching_rate=_model_switching_rate(details),
    )


def summarize_imported_details(
    details: list[SessionDetails],
    label: str = "imported",
    pricing: PricingConfig | None = None,
) -> TimeSummary:
    return summarize_details(label, details, pricing)


def local_date(value: datetime, timezone: tzinfo | None) -> datetime.date:
    target_timezone = timezone or value.astimezone().tzinfo
    return value.astimezone(target_timezone).date()


def summarize_models(paths: Paths) -> list[BreakdownEntry]:
    details = iter_session_details(paths)
    return summarize_models_from_details(details, load_pricing_config(paths))


def summarize_models_from_details(
    details: list[SessionDetails],
    pricing: PricingConfig | None = None,
) -> list[BreakdownEntry]:
    pricing = pricing or PricingConfig()
    grouped: dict[str, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        grouped[detail.session.model or "unknown"].append(detail)
    return _build_breakdown(grouped, pricing)


def summarize_projects(paths: Paths) -> list[BreakdownEntry]:
    details = iter_session_details(paths)
    return summarize_projects_from_details(details, load_pricing_config(paths))


def summarize_project_drilldown(
    paths: Paths,
    project_name: str,
    days: int | None = None,
    now: datetime | None = None,
) -> TimeSummary:
    pricing = load_pricing_config(paths)
    details = details_for_last_days(paths, days, now=now) if days else iter_session_details(paths)
    filtered = filter_details_by_project(details, project_name)
    label = project_name if days is None else f"{project_name} last {max(days, 1)} days"
    return summarize_details(label, filtered, pricing)


def summarize_projects_from_details(
    details: list[SessionDetails],
    pricing: PricingConfig | None = None,
) -> list[BreakdownEntry]:
    pricing = pricing or PricingConfig()
    grouped: dict[str, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        grouped[detail.session.project_name].append(detail)
    return _build_breakdown(grouped, pricing)


def summarize_history(paths: Paths, limit: int = 10) -> list[HistoryEntry]:
    details = iter_session_details(paths)
    return summarize_history_from_details(details, load_pricing_config(paths), limit=limit)


def summarize_history_from_details(
    details: list[SessionDetails],
    pricing: PricingConfig | None = None,
    limit: int = 10,
) -> list[HistoryEntry]:
    pricing = pricing or PricingConfig()
    ordered = sorted(
        details,
        key=lambda detail: detail.session.updated_at,
        reverse=True,
    )
    history: list[HistoryEntry] = []
    for detail in ordered[:limit]:
        history.append(
            HistoryEntry(
                session_id=detail.session.session_id,
                project_name=detail.session.project_name,
                model=detail.session.model,
                updated_at=detail.session.updated_at,
                total_tokens=detail.effective_total_tokens(),
                requests=detail.request_count,
                estimated_cost_usd=estimate_detail_cost(detail, pricing),
            )
        )
    return history


def summarize_daily(paths: Paths, days: int = 7, now: datetime | None = None) -> list[DailyPoint]:
    current_time = now or datetime.now().astimezone()
    safe_days = max(days, 1)
    details = details_for_last_days(paths, safe_days, now=current_time)
    pricing = load_pricing_config(paths)
    return summarize_daily_from_details(details, days=safe_days, now=current_time, pricing=pricing)


def summarize_daily_from_details(
    details: list[SessionDetails],
    *,
    days: int,
    now: datetime | None = None,
    pricing: PricingConfig | None = None,
) -> list[DailyPoint]:
    current_time = now or datetime.now().astimezone()
    safe_days = max(days, 1)
    pricing = pricing or PricingConfig()
    day_map: dict[date, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        day_map[local_date(detail.session.created_at, current_time.tzinfo)].append(detail)

    points: list[DailyPoint] = []
    for offset in range(safe_days):
        current_day = current_time.date() - timedelta(days=safe_days - 1 - offset)
        day_details = day_map.get(current_day, [])
        summary = summarize_details(current_day.isoformat(), day_details, pricing)
        points.append(
            DailyPoint(
                day=current_day.isoformat(),
                total_tokens=summary.total_tokens,
                requests=summary.requests,
                estimated_cost_usd=summary.estimated_cost_usd,
            )
        )
    return points


def summarize_compare(paths: Paths, days: int = 7, now: datetime | None = None) -> CompareReport:
    current_time = now or datetime.now().astimezone()
    safe_days = max(days, 1)
    pricing = load_pricing_config(paths)
    current_details = details_for_last_days(paths, safe_days, now=current_time)
    previous_end = current_time - timedelta(days=safe_days)
    previous_details = details_for_last_days(paths, safe_days, now=previous_end)
    return summarize_compare_from_details(
        current_details,
        previous_details,
        current_label=f"last {safe_days} days",
        previous_label=f"prev {safe_days} days",
        pricing=pricing,
    )


def summarize_compare_from_details(
    current_details: list[SessionDetails],
    previous_details: list[SessionDetails],
    *,
    current_label: str,
    previous_label: str,
    pricing: PricingConfig | None = None,
) -> CompareReport:
    pricing = pricing or PricingConfig()
    current_summary = summarize_details(current_label, current_details, pricing)
    previous_summary = summarize_details(previous_label, previous_details, pricing)
    total_tokens_delta = current_summary.total_tokens - previous_summary.total_tokens
    total_tokens_delta_pct = None
    if previous_summary.total_tokens:
        total_tokens_delta_pct = (total_tokens_delta / previous_summary.total_tokens) * 100.0
    return CompareReport(
        current=current_summary,
        previous=previous_summary,
        total_tokens_delta=total_tokens_delta,
        total_tokens_delta_pct=total_tokens_delta_pct,
        requests_delta=current_summary.requests - previous_summary.requests,
        cost_delta_usd=round(current_summary.estimated_cost_usd - previous_summary.estimated_cost_usd, 4),
    )


def summarize_compare_named(paths: Paths, current_label: str, previous_label: str, now: datetime | None = None) -> CompareReport:
    current_time = now or datetime.now().astimezone()
    pricing = load_pricing_config(paths)
    current_summary = _summary_for_named_window(paths, current_label, current_time, pricing)
    previous_summary = _summary_for_named_window(paths, previous_label, current_time, pricing)
    total_tokens_delta = current_summary.total_tokens - previous_summary.total_tokens
    total_tokens_delta_pct = None
    if previous_summary.total_tokens:
        total_tokens_delta_pct = (total_tokens_delta / previous_summary.total_tokens) * 100.0
    return CompareReport(
        current=current_summary,
        previous=previous_summary,
        total_tokens_delta=total_tokens_delta,
        total_tokens_delta_pct=total_tokens_delta_pct,
        requests_delta=current_summary.requests - previous_summary.requests,
        cost_delta_usd=round(current_summary.estimated_cost_usd - previous_summary.estimated_cost_usd, 4),
    )


def run_doctor(paths: Paths) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    checks.append(
        DoctorCheck(
            name="codex_home",
            ok=paths.codex_home.exists(),
            detail=f"Found {paths.codex_home}" if paths.codex_home.exists() else f"Missing {paths.codex_home}",
        )
    )
    checks.append(
        DoctorCheck(
            name="state_db",
            ok=paths.state_db.exists(),
            detail=f"Found {paths.state_db}" if paths.state_db.exists() else f"Missing {paths.state_db}",
        )
    )
    checks.append(
        DoctorCheck(
            name="sessions_dir",
            ok=paths.sessions_dir.exists(),
            detail=f"Found {paths.sessions_dir}" if paths.sessions_dir.exists() else f"Missing {paths.sessions_dir}",
        )
    )
    checks.append(
        DoctorCheck(
            name="config_file",
            ok=paths.config_file.exists(),
            detail=f"Found {paths.config_file}" if paths.config_file.exists() else f"Missing {paths.config_file}; using built-in defaults",
            severity="warning",
        )
    )
    details = iter_session_details(paths) if paths.state_db.exists() else []
    checks.append(
        DoctorCheck(
            name="session_count",
            ok=bool(details),
            detail=f"{len(details)} session(s) detected",
            severity="warning",
        )
    )
    rollout_count = sum(1 for detail in details if detail.session.rollout_path.exists())
    checks.append(
        DoctorCheck(
            name="rollout_files",
            ok=rollout_count == len(details),
            detail=f"{rollout_count}/{len(details)} rollout files present" if details else "No sessions to validate",
        )
    )
    token_snapshots = sum(1 for detail in details if detail.total_tokens_from_rollout is not None)
    checks.append(
        DoctorCheck(
            name="token_snapshots",
            ok=token_snapshots == len(details),
            detail=f"{token_snapshots}/{len(details)} sessions have rollout token snapshots" if details else "No sessions to validate",
            severity="warning",
        )
    )
    try:
        app_config = load_config(paths)
        checks.append(
            DoctorCheck(
                name="pricing_config",
                ok=True,
                detail=f"default={app_config.pricing.default_usd_per_1k_tokens:.4f}/1k, models={len(app_config.pricing.model_rates or {})}",
            )
        )
        checks.append(
            DoctorCheck(
                name="display_config",
                ok=True,
                detail=f"color={app_config.display.color}, history_limit={app_config.display.history_limit}, compare_days={app_config.display.compare_days}",
            )
        )
    except Exception as exc:
        checks.append(
            DoctorCheck(
                name="pricing_config",
                ok=False,
                detail=f"Invalid config: {exc}",
            )
        )
        checks.append(
            DoctorCheck(
                name="display_config",
                ok=False,
                detail=f"Invalid config: {exc}",
            )
        )
    return checks


def summarize_costs(paths: Paths, now: datetime | None = None) -> CostSummary:
    current_time = now or datetime.now().astimezone()
    pricing = load_pricing_config(paths)
    today = summarize_today(paths, now=current_time)
    week = summarize_week(paths, now=current_time)
    month = summarize_month(paths, now=current_time)
    details = iter_session_details(paths)
    return summarize_costs_from_details(details, pricing=pricing, today=today, week=week, month=month, now=current_time)


def summarize_costs_from_details(
    details: list[SessionDetails],
    *,
    pricing: PricingConfig | None = None,
    today: TimeSummary | None = None,
    week: TimeSummary | None = None,
    month: TimeSummary | None = None,
    now: datetime | None = None,
) -> CostSummary:
    current_time = now or datetime.now().astimezone()
    pricing = pricing or PricingConfig()
    today = today or summarize_details("today", details, pricing)
    week = week or summarize_details("week", details, pricing)
    month = month or summarize_details("month", details, pricing)
    month_start = current_time.date() - timedelta(days=29)
    active_days = {
        local_date(detail.session.created_at, current_time.tzinfo)
        for detail in details
        if month_start <= local_date(detail.session.created_at, current_time.tzinfo) <= current_time.date()
    }
    highest_session_cost_usd = max(
        (estimate_detail_cost(detail, pricing) for detail in details),
        default=0.0,
    )
    projected_monthly = month.estimated_cost_usd
    if active_days and month.estimated_cost_usd:
        projected_monthly = round((month.estimated_cost_usd / len(active_days)) * 30, 4)
    return CostSummary(
        today_cost_usd=today.estimated_cost_usd,
        week_cost_usd=week.estimated_cost_usd,
        month_cost_usd=month.estimated_cost_usd,
        projected_monthly_cost_usd=projected_monthly,
        highest_session_cost_usd=highest_session_cost_usd,
    )


def summarize_insights(paths: Paths, now: datetime | None = None) -> InsightReport:
    current_time = now or datetime.now().astimezone()
    pricing = load_pricing_config(paths)
    month = summarize_month(paths, now=current_time)
    details = iter_session_details(paths)
    return summarize_insights_from_details(details, pricing=pricing, month=month, now=current_time)


def summarize_insights_from_details(
    details: list[SessionDetails],
    *,
    pricing: PricingConfig | None = None,
    month: TimeSummary | None = None,
    now: datetime | None = None,
) -> InsightReport:
    current_time = now or datetime.now().astimezone()
    pricing = pricing or PricingConfig()
    month = month or summarize_details("month", details, pricing)
    large_session_threshold = 100_000
    large_session_count = sum(1 for detail in details if detail.effective_total_tokens() >= large_session_threshold)
    cache_ratio = month.cache_ratio
    possible_savings_usd = 0.0
    suggestion = "Usage looks balanced."
    anomalies: list[str] = []
    recommendations: list[str] = []
    highest_session_tokens = month.largest_session_tokens
    if details:
        session_totals = sorted((detail.effective_total_tokens() for detail in details), reverse=True)
        total_tokens = sum(session_totals)
        if total_tokens and session_totals[0] / total_tokens >= 0.6:
            anomalies.append("Heavy cost concentration in one session")
            recommendations.append("Split exploratory work into smaller sessions.")
        if len(session_totals) >= 2 and session_totals[0] >= session_totals[1] * 3:
            anomalies.append("Sudden usage spike relative to your other sessions")
            recommendations.append("Review the largest session and reset context earlier.")
    if highest_session_tokens >= 1_000_000:
        anomalies.append("Oversized session detected")
        recommendations.append("Break implementation and research into separate runs.")
    if cache_ratio is not None and cache_ratio < 0.25:
        possible_savings_usd = round(month.estimated_cost_usd * 0.15, 2)
        suggestion = "Cache reuse is low. Reuse context or break work into steadier sessions."
        anomalies.append("Low cache efficiency")
        recommendations.append("Reuse context and avoid restarting similar prompts.")
    elif month.average_tokens_per_request > 50_000:
        possible_savings_usd = round(month.estimated_cost_usd * 0.1, 2)
        suggestion = "Requests are very large. Reset context more aggressively between tasks."
        anomalies.append("Requests are unusually large")
        recommendations.append("Trim prompts and summarize progress between tasks.")
    elif large_session_count > 0:
        possible_savings_usd = round(month.estimated_cost_usd * 0.05, 2)
        suggestion = "Large sessions detected. Consider shorter task-focused runs."
        recommendations.append("Use shorter, task-focused sessions.")

    if not recommendations:
        recommendations.append("Current usage patterns look healthy.")

    return InsightReport(
        average_tokens_per_request=month.average_tokens_per_request,
        cache_ratio=cache_ratio,
        large_session_count=large_session_count,
        possible_savings_usd=possible_savings_usd,
        largest_session_tokens=month.largest_session_tokens,
        suggestion=suggestion,
        anomalies=anomalies,
        recommendations=recommendations,
    )


def build_watch_alerts(
    summary: TimeSummary,
    compare: CompareReport,
    insights: InsightReport,
    *,
    cost_threshold_usd: float | None = None,
    token_threshold: int | None = None,
    request_threshold: int | None = None,
    delta_pct_threshold: float | None = None,
) -> list[WatchAlert]:
    alerts: list[WatchAlert] = []

    if cost_threshold_usd is not None and summary.estimated_cost_usd >= cost_threshold_usd:
        alerts.append(
            WatchAlert(
                severity="critical",
                name="cost_threshold",
                detail=f"Estimated cost ${summary.estimated_cost_usd:.2f} exceeded threshold ${cost_threshold_usd:.2f}.",
            )
        )
    if token_threshold is not None and summary.total_tokens >= token_threshold:
        alerts.append(
            WatchAlert(
                severity="critical",
                name="token_threshold",
                detail=f"Total tokens {summary.total_tokens:,} exceeded threshold {token_threshold:,}.",
            )
        )
    if request_threshold is not None and summary.requests >= request_threshold:
        alerts.append(
            WatchAlert(
                severity="warning",
                name="request_threshold",
                detail=f"Requests {summary.requests} exceeded threshold {request_threshold}.",
            )
        )
    if (
        delta_pct_threshold is not None
        and compare.total_tokens_delta_pct is not None
        and compare.total_tokens_delta_pct >= delta_pct_threshold
    ):
        alerts.append(
            WatchAlert(
                severity="warning",
                name="token_delta",
                detail=f"Token usage increased {compare.total_tokens_delta_pct:.1f}% versus the previous window.",
            )
        )
    if compare.total_tokens_delta_pct is not None and compare.total_tokens_delta_pct >= 200.0:
        alerts.append(
            WatchAlert(
                severity="critical",
                name="token_spike",
                detail=f"Token usage spiked {compare.total_tokens_delta_pct:.1f}% versus the previous window.",
            )
        )
    elif compare.total_tokens_delta_pct is not None and compare.total_tokens_delta_pct >= 50.0:
        alerts.append(
            WatchAlert(
                severity="warning",
                name="token_spike",
                detail=f"Token usage rose {compare.total_tokens_delta_pct:.1f}% versus the previous window.",
            )
        )

    anomaly_severity = {
        "Oversized session detected": "critical",
        "Requests are unusually large": "critical",
        "Heavy cost concentration in one session": "warning",
        "Sudden usage spike relative to your other sessions": "warning",
        "Low cache efficiency": "warning",
    }
    for anomaly in insights.anomalies:
        alerts.append(
            WatchAlert(
                severity=anomaly_severity.get(anomaly, "warning"),
                name="insight_anomaly",
                detail=anomaly,
            )
        )

    if insights.large_session_count >= 3:
        alerts.append(
            WatchAlert(
                severity="warning",
                name="large_sessions",
                detail=f"{insights.large_session_count} large sessions detected in the current window.",
            )
        )

    deduped: dict[tuple[str, str], WatchAlert] = {}
    for alert in alerts:
        key = (alert.name, alert.detail)
        existing = deduped.get(key)
        if existing is None or existing.severity == "warning" and alert.severity == "critical":
            deduped[key] = alert
    return list(deduped.values())


def apply_watch_state(
    details: list[SessionDetails],
    alerts: list[WatchAlert],
    *,
    seen_session_ids: set[str] | None = None,
    seen_alert_keys: set[tuple[str, str]] | None = None,
    baseline_ready: bool = False,
) -> tuple[list[WatchAlert], set[str], set[tuple[str, str]]]:
    seen_session_ids = set(seen_session_ids or set())
    seen_alert_keys = set(seen_alert_keys or set())
    current_session_ids = {detail.session.session_id for detail in details}
    current_alert_keys = {(alert.name, alert.detail) for alert in alerts}

    new_session_alerts: list[WatchAlert] = []
    if baseline_ready:
        new_session_ids = sorted(current_session_ids - seen_session_ids)
        for session_id in new_session_ids:
            detail = next(detail for detail in details if detail.session.session_id == session_id)
            new_session_alerts.append(
                WatchAlert(
                    severity="warning",
                    name="new_session",
                    detail=(
                        f"New session in {detail.session.project_name} using {detail.session.model or 'unknown'} "
                        f"with {detail.effective_total_tokens():,} tokens so far."
                    ),
                    is_new=True,
                )
            )

    enriched_alerts: list[WatchAlert] = []
    for alert in alerts:
        key = (alert.name, alert.detail)
        enriched_alerts.append(
            WatchAlert(
                severity=alert.severity,
                name=alert.name,
                detail=alert.detail,
                is_new=baseline_ready and key not in seen_alert_keys,
            )
        )

    updated_alerts = new_session_alerts + enriched_alerts
    return updated_alerts, current_session_ids, current_alert_keys | {(alert.name, alert.detail) for alert in new_session_alerts}


def summarize_top_sessions(paths: Paths, limit: int = 5) -> list[TopEntry]:
    return summarize_top_sessions_from_details(iter_session_details(paths), load_pricing_config(paths), limit=limit)


def summarize_activity_heatmap(
    paths: Paths,
    *,
    days: int | None = None,
    now: datetime | None = None,
) -> list[HeatmapCell]:
    details = details_for_last_days(paths, days, now=now) if days else iter_session_details(paths)
    timezone = (now or datetime.now().astimezone()).tzinfo
    return summarize_activity_heatmap_from_details(details, timezone=timezone)


def summarize_activity_heatmap_from_details(
    details: list[SessionDetails],
    *,
    timezone: tzinfo | None,
) -> list[HeatmapCell]:
    buckets: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: {"session_count": 0, "total_tokens": 0})
    for detail in details:
        started = detail.started_at or detail.session.created_at
        local_started = started.astimezone(timezone or started.astimezone().tzinfo)
        key = (local_started.weekday(), local_started.hour)
        buckets[key]["session_count"] += 1
        buckets[key]["total_tokens"] += detail.effective_total_tokens()
    return [
        HeatmapCell(
            weekday=weekday,
            hour=hour,
            session_count=bucket["session_count"],
            total_tokens=bucket["total_tokens"],
        )
        for (weekday, hour), bucket in sorted(buckets.items())
    ]


def summarize_top_sessions_from_details(
    details: list[SessionDetails],
    pricing: PricingConfig | None = None,
    limit: int = 5,
    project_name: str | None = None,
) -> list[TopEntry]:
    pricing = pricing or PricingConfig()
    filtered = filter_details_by_project(details, project_name)
    ordered = sorted(filtered, key=lambda detail: detail.effective_total_tokens(), reverse=True)
    return [
        TopEntry(
            session_id=detail.session.session_id,
            project_name=detail.session.project_name,
            model=detail.session.model,
            total_tokens=detail.effective_total_tokens(),
            requests=detail.request_count,
            estimated_cost_usd=estimate_detail_cost(detail, pricing),
        )
        for detail in ordered[:limit]
    ]


def build_report(
    paths: Paths,
    period: str = "weekly",
    project_name: str | None = None,
    now: datetime | None = None,
) -> ReportData:
    current_time = now or datetime.now().astimezone()
    pricing = load_pricing_config(paths)
    if period == "weekly":
        details = details_for_last_days(paths, 7, now=current_time)
        previous = summarize_compare_named(paths, "week", "last-week", now=current_time)
    elif period == "monthly":
        details = details_for_last_days(paths, 30, now=current_time)
        previous = summarize_compare_named(paths, "month", "last-month", now=current_time)
    else:
        raise ValueError(f"Unsupported period: {period}")

    filtered_details = filter_details_by_project(details, project_name)
    label = period if project_name is None else f"{period} {project_name}"
    summary = summarize_details(label, filtered_details, pricing)
    if project_name is not None:
        previous_current = filter_details_by_project(details_for_last_days(paths, 7 if period == "weekly" else 30, now=current_time), project_name)
        previous_previous = filter_details_by_project(
            details_for_last_days(paths, 7 if period == "weekly" else 30, now=current_time - timedelta(days=7 if period == "weekly" else 30)),
            project_name,
        )
        previous = CompareReport(
            current=summarize_details(summary.label, previous_current, pricing),
            previous=summarize_details(
                f"prev {period}",
                previous_previous,
                pricing,
            ),
            total_tokens_delta=0,
            total_tokens_delta_pct=None,
            requests_delta=0,
            cost_delta_usd=0.0,
        )
        total_tokens_delta = previous.current.total_tokens - previous.previous.total_tokens
        total_tokens_delta_pct = None
        if previous.previous.total_tokens:
            total_tokens_delta_pct = (total_tokens_delta / previous.previous.total_tokens) * 100.0
        previous = CompareReport(
            current=previous.current,
            previous=previous.previous,
            total_tokens_delta=total_tokens_delta,
            total_tokens_delta_pct=total_tokens_delta_pct,
            requests_delta=previous.current.requests - previous.previous.requests,
            cost_delta_usd=round(previous.current.estimated_cost_usd - previous.previous.estimated_cost_usd, 4),
        )

    report = ReportData(
        period=period,
        project_name=project_name,
        summary=summary,
        comparison=previous,
        projects=summarize_projects_from_details(filtered_details, pricing)[:5] if project_name is None else [],
        top_sessions=summarize_top_sessions_from_details(filtered_details, pricing, limit=5),
        costs=summarize_costs_from_details(filtered_details, pricing=pricing, today=summary, week=summary, month=summary, now=current_time),
        insights=summarize_insights_from_details(filtered_details, pricing=pricing, month=summary, now=current_time),
        activity_heatmap=summarize_activity_heatmap_from_details(filtered_details, timezone=current_time.tzinfo),
    )
    return report


def _build_breakdown(grouped: dict[str, list[SessionDetails]], pricing: PricingConfig) -> list[BreakdownEntry]:
    entries: list[BreakdownEntry] = []
    for name, details in grouped.items():
        total_tokens = sum(detail.effective_total_tokens() for detail in details)
        entries.append(
            BreakdownEntry(
                name=name,
                sessions=len(details),
                requests=sum(detail.request_count for detail in details),
                total_tokens=total_tokens,
                estimated_cost_usd=round(sum(estimate_detail_cost(detail, pricing) for detail in details), 4),
            )
        )
    return sorted(entries, key=lambda entry: (-entry.total_tokens, entry.name))


def _summary_for_named_window(
    paths: Paths,
    label: str,
    now: datetime,
    pricing: PricingConfig,
) -> TimeSummary:
    day = now.date()
    if label == "today":
        details = details_for_last_days(paths, 1, now=now)
        return summarize_details("today", details, pricing)
    if label == "yesterday":
        details = details_for_last_days(paths, 1, now=now - timedelta(days=1))
        return summarize_details("yesterday", details, pricing)
    if label == "week":
        details = details_for_last_days(paths, 7, now=now)
        return summarize_details("week", details, pricing)
    if label == "last-week":
        details = details_for_last_days(paths, 7, now=now - timedelta(days=7))
        return summarize_details("last-week", details, pricing)
    if label == "month":
        details = details_for_last_days(paths, 30, now=now)
        return summarize_details("month", details, pricing)
    if label == "last-month":
        details = details_for_last_days(paths, 30, now=now - timedelta(days=30))
        return summarize_details("last-month", details, pricing)
    raise ValueError(f"Unsupported compare label: {label}")


def _project_concentration(details: list[SessionDetails], *, top_n: int) -> float | None:
    if not details:
        return None
    project_totals: dict[str, int] = defaultdict(int)
    total_tokens = 0
    for detail in details:
        tokens = detail.effective_total_tokens()
        total_tokens += tokens
        project_totals[detail.session.project_name] += tokens
    if total_tokens <= 0:
        return None
    ranked = sorted(project_totals.values(), reverse=True)
    return sum(ranked[:top_n]) / total_tokens


def _longest_active_streak_days(details: list[SessionDetails]) -> int:
    active_days = sorted({detail.session.created_at.astimezone().date() for detail in details})
    if not active_days:
        return 0
    longest = 1
    current = 1
    for previous, current_day in zip(active_days, active_days[1:]):
        if (current_day - previous).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest


def _model_switching_rate(details: list[SessionDetails]) -> float | None:
    ordered_models = [detail.session.model or "unknown" for detail in sorted(details, key=lambda detail: detail.session.created_at)]
    if len(ordered_models) < 2:
        return None
    switches = sum(1 for previous, current in zip(ordered_models, ordered_models[1:]) if previous != current)
    transitions = len(ordered_models) - 1
    return switches / transitions if transitions else None
