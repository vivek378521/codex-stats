from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, tzinfo

from .config import Paths
from .ingest import get_session_details, iter_session_details
from .models import BreakdownEntry, SessionDetails, TimeSummary

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
    )


def local_date(value: datetime, timezone: tzinfo | None) -> datetime.date:
    target_timezone = timezone or value.astimezone().tzinfo
    return value.astimezone(target_timezone).date()


def summarize_models(paths: Paths) -> list[BreakdownEntry]:
    details = iter_session_details(paths)
    grouped: dict[str, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        grouped[detail.session.model or "unknown"].append(detail)
    return _build_breakdown(grouped)


def summarize_projects(paths: Paths) -> list[BreakdownEntry]:
    details = iter_session_details(paths)
    grouped: dict[str, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        grouped[detail.session.project_name].append(detail)
    return _build_breakdown(grouped)


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
