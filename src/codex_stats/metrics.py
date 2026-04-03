from __future__ import annotations

from collections import Counter
from datetime import datetime, tzinfo

from .config import Paths
from .ingest import get_session_details, sessions_for_day
from .models import SessionDetails, TimeSummary

# Conservative placeholder pricing. Replace with model-specific pricing later.
DEFAULT_USD_PER_1K_TOKENS = 0.01


def estimate_cost_usd(total_tokens: int, usd_per_1k_tokens: float = DEFAULT_USD_PER_1K_TOKENS) -> float:
    return round((total_tokens / 1000.0) * usd_per_1k_tokens, 4)


def summarize_today(paths: Paths, now: datetime | None = None) -> TimeSummary:
    current_time = now or datetime.now().astimezone()
    timezone = current_time.tzinfo
    sessions = sessions_for_day(paths, current_time.date(), timezone)
    details = [get_session_details(paths, session) for session in sessions]
    return summarize_details("today", details)


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
