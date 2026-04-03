from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, tzinfo

from .config import Paths
from .ingest import get_session_details, iter_session_details
from .models import BreakdownEntry, CostSummary, HistoryEntry, InsightReport, SessionDetails, TimeSummary

# Conservative placeholder pricing. Replace with model-specific pricing later.
DEFAULT_USD_PER_1K_TOKENS = 0.01


def estimate_cost_usd(total_tokens: int, usd_per_1k_tokens: float = DEFAULT_USD_PER_1K_TOKENS) -> float:
    return round((total_tokens / 1000.0) * usd_per_1k_tokens, 4)


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
    return summarize_details(label, details)


def summarize_details(label: str, details: list[SessionDetails]) -> TimeSummary:
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
        estimated_cost_usd=estimate_cost_usd(total_tokens),
        top_model=top_model,
        average_tokens_per_request=average_tokens_per_request,
        cache_ratio=cache_ratio,
        largest_session_tokens=largest_session_tokens,
    )


def summarize_imported_details(details: list[SessionDetails], label: str = "imported") -> TimeSummary:
    return summarize_details(label, details)


def local_date(value: datetime, timezone: tzinfo | None) -> datetime.date:
    target_timezone = timezone or value.astimezone().tzinfo
    return value.astimezone(target_timezone).date()


def summarize_models(paths: Paths) -> list[BreakdownEntry]:
    details = iter_session_details(paths)
    return summarize_models_from_details(details)


def summarize_models_from_details(details: list[SessionDetails]) -> list[BreakdownEntry]:
    grouped: dict[str, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        grouped[detail.session.model or "unknown"].append(detail)
    return _build_breakdown(grouped)


def summarize_projects(paths: Paths) -> list[BreakdownEntry]:
    details = iter_session_details(paths)
    return summarize_projects_from_details(details)


def summarize_projects_from_details(details: list[SessionDetails]) -> list[BreakdownEntry]:
    grouped: dict[str, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        grouped[detail.session.project_name].append(detail)
    return _build_breakdown(grouped)


def summarize_history(paths: Paths, limit: int = 10) -> list[HistoryEntry]:
    details = iter_session_details(paths)
    return summarize_history_from_details(details, limit=limit)


def summarize_history_from_details(details: list[SessionDetails], limit: int = 10) -> list[HistoryEntry]:
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
                estimated_cost_usd=estimate_cost_usd(detail.effective_total_tokens()),
            )
        )
    return history


def summarize_costs(paths: Paths, now: datetime | None = None) -> CostSummary:
    current_time = now or datetime.now().astimezone()
    today = summarize_today(paths, now=current_time)
    week = summarize_week(paths, now=current_time)
    month = summarize_month(paths, now=current_time)
    details = iter_session_details(paths)
    return summarize_costs_from_details(details, today=today, week=week, month=month, now=current_time)


def summarize_costs_from_details(
    details: list[SessionDetails],
    *,
    today: TimeSummary | None = None,
    week: TimeSummary | None = None,
    month: TimeSummary | None = None,
    now: datetime | None = None,
) -> CostSummary:
    current_time = now or datetime.now().astimezone()
    today = today or summarize_details("today", details)
    week = week or summarize_details("week", details)
    month = month or summarize_details("month", details)
    month_start = current_time.date() - timedelta(days=29)
    active_days = {
        local_date(detail.session.created_at, current_time.tzinfo)
        for detail in details
        if month_start <= local_date(detail.session.created_at, current_time.tzinfo) <= current_time.date()
    }
    highest_session_cost_usd = max(
        (estimate_cost_usd(detail.effective_total_tokens()) for detail in details),
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
    month = summarize_month(paths, now=current_time)
    details = iter_session_details(paths)
    return summarize_insights_from_details(details, month=month, now=current_time)


def summarize_insights_from_details(
    details: list[SessionDetails],
    *,
    month: TimeSummary | None = None,
    now: datetime | None = None,
) -> InsightReport:
    current_time = now or datetime.now().astimezone()
    month = month or summarize_details("month", details)
    large_session_threshold = 100_000
    large_session_count = sum(1 for detail in details if detail.effective_total_tokens() >= large_session_threshold)
    cache_ratio = month.cache_ratio
    possible_savings_usd = 0.0
    suggestion = "Usage looks balanced."
    if cache_ratio is not None and cache_ratio < 0.25:
        possible_savings_usd = round(month.estimated_cost_usd * 0.15, 2)
        suggestion = "Cache reuse is low. Reuse context or break work into steadier sessions."
    elif month.average_tokens_per_request > 50_000:
        possible_savings_usd = round(month.estimated_cost_usd * 0.1, 2)
        suggestion = "Requests are very large. Reset context more aggressively between tasks."
    elif large_session_count > 0:
        possible_savings_usd = round(month.estimated_cost_usd * 0.05, 2)
        suggestion = "Large sessions detected. Consider shorter task-focused runs."

    return InsightReport(
        average_tokens_per_request=month.average_tokens_per_request,
        cache_ratio=cache_ratio,
        large_session_count=large_session_count,
        possible_savings_usd=possible_savings_usd,
        largest_session_tokens=month.largest_session_tokens,
        suggestion=suggestion,
    )


def _build_breakdown(grouped: dict[str, list[SessionDetails]]) -> list[BreakdownEntry]:
    entries: list[BreakdownEntry] = []
    for name, details in grouped.items():
        total_tokens = sum(detail.effective_total_tokens() for detail in details)
        entries.append(
            BreakdownEntry(
                name=name,
                sessions=len(details),
                requests=sum(detail.request_count for detail in details),
                total_tokens=total_tokens,
                estimated_cost_usd=estimate_cost_usd(total_tokens),
            )
        )
    return sorted(entries, key=lambda entry: (-entry.total_tokens, entry.name))
