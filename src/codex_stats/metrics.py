from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, tzinfo
import re

from .config import Paths, PricingConfig, load_pricing_config
from .ingest import get_session_details, iter_session_details
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
    TopEntry,
    ReportData,
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
    current_summary = summarize_details(f"last {safe_days} days", current_details, pricing)
    previous_summary = summarize_details(f"prev {safe_days} days", previous_details, pricing)
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
            detail=f"Found {paths.config_file}" if paths.config_file.exists() else f"Missing {paths.config_file}",
        )
    )
    details = iter_session_details(paths) if paths.state_db.exists() else []
    checks.append(
        DoctorCheck(
            name="session_count",
            ok=bool(details),
            detail=f"{len(details)} session(s) detected",
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
    try:
        pricing = load_pricing_config(paths)
        checks.append(
            DoctorCheck(
                name="pricing_config",
                ok=True,
                detail=f"default={pricing.default_usd_per_1k_tokens:.4f}/1k, models={len(pricing.model_rates or {})}",
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


def summarize_top_sessions(paths: Paths, limit: int = 5) -> list[TopEntry]:
    return summarize_top_sessions_from_details(iter_session_details(paths), load_pricing_config(paths), limit=limit)


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


def build_report(paths: Paths, period: str = "weekly", now: datetime | None = None) -> ReportData:
    current_time = now or datetime.now().astimezone()
    pricing = load_pricing_config(paths)
    if period == "weekly":
        details = details_for_last_days(paths, 7, now=current_time)
        summary = summarize_details("weekly", details, pricing)
        previous = summarize_compare_named(paths, "week", "last-week", now=current_time)
    elif period == "monthly":
        details = details_for_last_days(paths, 30, now=current_time)
        summary = summarize_details("monthly", details, pricing)
        previous = summarize_compare_named(paths, "month", "last-month", now=current_time)
    else:
        raise ValueError(f"Unsupported period: {period}")

    report = ReportData(
        period=period,
        summary=summary,
        comparison=previous,
        projects=summarize_projects_from_details(details, pricing)[:5],
        top_sessions=summarize_top_sessions_from_details(details, pricing, limit=5),
        costs=summarize_costs_from_details(details, pricing=pricing, today=summary, week=summary, month=summary, now=current_time),
        insights=summarize_insights_from_details(details, pricing=pricing, month=summary, now=current_time),
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
