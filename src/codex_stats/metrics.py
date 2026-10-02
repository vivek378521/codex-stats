from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, tzinfo
from statistics import median

from .config import PricingConfig
from .models import (
    TOOL_CATEGORY_EDIT,
    TOOL_CATEGORY_LABELS,
    TOOL_CATEGORY_ORDER,
    TOOL_CATEGORY_OTHER,
    TOOL_CATEGORY_READ,
    BehaviorSummary,
    BranchActivity,
    BranchSummary,
    BreakdownEntry,
    CompareReport,
    CostSummary,
    DashboardBadge,
    DailyPoint,
    FileImpactEntry,
    HeatmapCell,
    HistoryEntry,
    InsightReport,
    ProjectDrilldown,
    SessionSpotlight,
    SessionDetails,
    TimeSummary,
    TokenSplit,
    ToolCategoryEntry,
    ToolDailyPoint,
    ToolUsageEntry,
    TopEntry,
    WorkRhythm,
)
from .sources import source_label

def uses_recorded_cost(detail: SessionDetails) -> bool:
    """Whether a session's cost comes from the tool's own figure rather than an estimate.

    A recorded 0 is treated as no usable figure, so those sessions are estimated and must
    also be reported as unrated when the model has no published rate.
    """
    return detail.recorded_cost_usd is not None and detail.recorded_cost_usd > 0


def estimate_detail_cost(detail: SessionDetails, pricing: PricingConfig) -> float:
    if uses_recorded_cost(detail):
        return round(detail.recorded_cost_usd, 4)
    rates, _ = pricing.rates_for(detail.session.source, detail.session.model)
    return rates.cost_for(detail.token_split())


def filter_details_by_project(details: list[SessionDetails], project_name: str | None) -> list[SessionDetails]:
    if not project_name:
        return details
    lowered = project_name.lower()
    return [detail for detail in details if detail.session.project_name.lower() == lowered]


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
    split = TokenSplit()
    for detail in details:
        part = detail.token_split()
        split = TokenSplit(
            fresh_input=split.fresh_input + part.fresh_input,
            cached_read=split.cached_read + part.cached_read,
            cache_write=split.cache_write + part.cache_write,
            output=split.output + part.output,
        )
    cache_ratio = split.cache_ratio()
    unrated_sessions = sum(
        1
        for detail in details
        if not uses_recorded_cost(detail)
        and pricing.rates_for(detail.session.source, detail.session.model)[1]
    )
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
        fresh_input_tokens=split.fresh_input,
        cache_read_tokens=split.cached_read,
        cache_write_tokens=split.cache_write,
        unrated_sessions=unrated_sessions,
    )


def local_date(value: datetime, timezone: tzinfo | None) -> datetime.date:
    target_timezone = timezone or value.astimezone().tzinfo
    return value.astimezone(target_timezone).date()


def summarize_source_breakdown_from_details(
    details: list[SessionDetails],
    pricing: PricingConfig | None = None,
    labels: dict[str, str] | None = None,
) -> list[BreakdownEntry]:
    pricing = pricing or PricingConfig()
    grouped: dict[str, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        grouped[detail.session.source].append(detail)
    entries: list[BreakdownEntry] = []
    for source_key, source_details in grouped.items():
        label = (labels or {}).get(source_key, source_label(source_key))
        total_tokens = sum(detail.effective_total_tokens() for detail in source_details)
        entries.append(
            BreakdownEntry(
                name=label,
                sessions=len(source_details),
                requests=sum(detail.request_count for detail in source_details),
                total_tokens=total_tokens,
                estimated_cost_usd=round(sum(estimate_detail_cost(detail, pricing) for detail in source_details), 4),
            )
        )
    return sorted(entries, key=lambda entry: (-entry.total_tokens, entry.name))


def summarize_source_daily_from_details(
    details: list[SessionDetails],
    *,
    days: int,
    now: datetime | None = None,
    pricing: PricingConfig | None = None,
) -> list[ToolDailyPoint]:
    pricing = pricing or PricingConfig()
    current_time = now or datetime.now().astimezone()
    safe_days = max(days, 1)
    end_day = current_time.date()
    start_day = end_day - timedelta(days=safe_days - 1)
    buckets: dict[tuple[date, str], list[SessionDetails]] = defaultdict(list)
    for detail in details:
        day = local_date(detail.session.created_at, current_time.tzinfo)
        if start_day <= day <= end_day:
            buckets[(day, detail.session.source)].append(detail)
    points = []
    for (day, source_key), source_details in sorted(buckets.items()):
        points.append(
            ToolDailyPoint(
                day=day.isoformat()[:10],
                source=source_key,
                total_tokens=sum(detail.effective_total_tokens() for detail in source_details),
                estimated_cost_usd=round(sum(estimate_detail_cost(detail, pricing) for detail in source_details), 4),
            )
        )
    return points


def summarize_projects_from_details(
    details: list[SessionDetails],
    pricing: PricingConfig | None = None,
) -> list[BreakdownEntry]:
    pricing = pricing or PricingConfig()
    grouped: dict[str, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        grouped[detail.session.project_name].append(detail)
    return _build_breakdown(grouped, pricing)


# Matched against the bare model name, as a prefix or as a hyphen-delimited segment,
# so "gpt-5.1-codex-mini" and "anthropic/claude-opus-4.6" both resolve. No entry is a
# prefix of another, so the order does not decide anything.
_VENDOR_MODEL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("gpt-", "OpenAI"),
    ("chatgpt", "OpenAI"),
    ("codex", "OpenAI"),
    ("o1-", "OpenAI"),
    ("o3-", "OpenAI"),
    ("o4-", "OpenAI"),
    ("claude", "Anthropic"),
    ("gemini", "Google"),
    ("gemma", "Google"),
    ("llama", "Meta"),
    ("mistral", "Mistral"),
    ("mixtral", "Mistral"),
    ("deepseek", "DeepSeek"),
    ("qwen", "Alibaba"),
    ("grok", "xAI"),
)

_UNIDENTIFIED_VENDOR = "Unidentified"

# Public label, so the renderer can recognise the bucket without duplicating the string.
UNIDENTIFIED_VENDOR_LABEL = _UNIDENTIFIED_VENDOR

_KNOWN_VENDOR_NAMES: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "gemini": "Google",
    "meta": "Meta",
    "mistral": "Mistral",
    "deepseek": "DeepSeek",
    "alibaba": "Alibaba",
    "xai": "xAI",
    "azure": "Azure",
    "bedrock": "Bedrock",
    "vertex": "Vertex",
}


def model_vendor(model: str | None, provider: str | None = None) -> str:
    """Resolve the billing vendor behind a model name.

    ``SessionRecord.model_provider`` cannot be grouped on directly: Codex records
    the real vendor (``openai``), but the OpenCode and Hermes sources record their
    own CLI name there instead (``opencode``, ``hermes``), and those two may route to
    any vendor underneath. Grouping on that field would answer "which CLI" while
    claiming to answer "which vendor".

    So the model name decides, with any ``vendor/`` prefix stripped first, because
    Hermes and Claude Code write ``anthropic/claude-opus-4.6`` where Codex writes a
    bare ``gpt-5.4``. The recorded provider is only a fallback for names no keyword
    claims, which keeps unknown aliases attributed to something rather than dropped.

    Some tools record an internal codename rather than a model name at all (this
    machine's OpenCode sessions all read ``big-pickle``), and no keyword can resolve
    that. Those land in "Unidentified" rather than being guessed at, which is the
    same honest bucket the pricing fallback already uses for those sessions.
    """
    if model:
        bare = model.rsplit("/", 1)[-1].lower()
        for prefix, vendor in _VENDOR_MODEL_PREFIXES:
            if bare.startswith(prefix) or f"-{prefix}" in bare:
                return vendor
    if provider:
        # A router or CLI name is not a vendor, so it is only used when it already
        # looks like one; otherwise the model name remains the honest answer.
        normalized = provider.strip().lower()
        if normalized in _KNOWN_VENDOR_NAMES:
            return _KNOWN_VENDOR_NAMES[normalized]
    return _UNIDENTIFIED_VENDOR


def summarize_providers_from_details(
    details: list[SessionDetails],
    pricing: PricingConfig | None = None,
) -> list[BreakdownEntry]:
    """Group spend by billing vendor, which is the question a bill actually asks."""
    pricing = pricing or PricingConfig()
    grouped: dict[str, list[SessionDetails]] = defaultdict(list)
    for detail in details:
        grouped[model_vendor(detail.session.model, detail.session.model_provider)].append(detail)
    return _build_breakdown(grouped, pricing)


DEFAULT_IDLE_BRANCH_DAYS = 14


def summarize_branches_from_details(
    details: list[SessionDetails],
    *,
    pricing: PricingConfig | None = None,
    now: datetime | None = None,
    limit: int = 8,
    idle_days: int = DEFAULT_IDLE_BRANCH_DAYS,
) -> BranchSummary:
    """Break spend down by branch, and surface the branches that went quiet.

    Projects are the natural unit for a dashboard but they are too coarse to answer
    "where did the money go": every branch of a repository lands in one project
    number, so work that was abandoned and work that shipped look identical. This
    groups by repository *and* branch, because a branch name is only unique inside
    its own checkout.

    A branch is idle once nothing has touched it for ``idle_days``. That is the
    point of the panel: a branch that consumed tokens and then stopped is work that
    was paid for and never finished, which no other panel can see.
    """
    pricing = pricing or PricingConfig()
    current_time = now or datetime.now().astimezone()
    tracked = [detail for detail in details if detail.session.git_branch]
    if not tracked:
        return BranchSummary(
            branches=[],
            tracked_sessions=0,
            total_sessions=len(details),
            idle_branches=[],
            supported=False,
        )

    grouped: dict[tuple[str, str], list[SessionDetails]] = defaultdict(list)
    for detail in tracked:
        grouped[(detail.session.project_name, detail.session.git_branch or "")].append(detail)

    branches: list[BranchActivity] = []
    for (project_name, branch_name), branch_details in grouped.items():
        last_at = max(detail.session.updated_at for detail in branch_details)
        first_at = min(detail.session.created_at for detail in branch_details)
        idle = max((current_time - last_at).days, 0)
        branches.append(
            BranchActivity(
                name=branch_name,
                project_name=project_name,
                sessions=len(branch_details),
                requests=sum(detail.request_count for detail in branch_details),
                total_tokens=sum(detail.effective_total_tokens() for detail in branch_details),
                estimated_cost_usd=round(
                    sum(estimate_detail_cost(detail, pricing) for detail in branch_details), 4
                ),
                first_at=first_at,
                last_at=last_at,
                idle_days=idle,
            )
        )

    # Ranked by cost, because "where did the money go" is a cost question. Ties fall
    # back to recency so the ordering is stable between runs.
    branches.sort(key=lambda branch: (-branch.estimated_cost_usd, -branch.last_at.timestamp(), branch.name))
    idle_branches = sorted(
        (branch for branch in branches if branch.idle_days >= max(idle_days, 0)),
        key=lambda branch: (-branch.estimated_cost_usd, branch.name),
    )
    return BranchSummary(
        branches=branches[: max(limit, 0)],
        tracked_sessions=len(tracked),
        total_sessions=len(details),
        idle_branches=idle_branches[: max(limit, 0)],
        supported=True,
    )


def summarize_branch_takeaways(branches: BranchSummary | None) -> list[str]:
    if branches is None or not branches.supported or not branches.branches:
        return []
    lines: list[str] = []
    if branches.idle_branches:
        # Labelled with the repository, because two projects can each have a "main"
        # and listing bare branch names would name the same thing twice.
        names = ", ".join(branch.label for branch in branches.idle_branches[:2])
        extra = len(branches.idle_branches) - 2
        suffix = f", and {extra} more" if extra > 0 else ""
        lines.append(
            f"{len(branches.idle_branches)} branch"
            f"{'es' if len(branches.idle_branches) != 1 else ''} went quiet after costing "
            f"${branches.idle_cost_usd:.2f} ({names}{suffix})."
        )
    longest = max(branches.branches, key=lambda branch: branch.sessions, default=None)
    if longest and longest.sessions >= 3:
        lines.append(
            f"{longest.label} took {longest.sessions} sessions at "
            f"{longest.tokens_per_session:,.0f} tokens each."
        )
    return lines


def summarize_project_drilldowns_from_details(
    details: list[SessionDetails],
    *,
    days: int,
    now: datetime | None = None,
    pricing: PricingConfig | None = None,
    limit: int = 5,
) -> list[ProjectDrilldown]:
    pricing = pricing or PricingConfig()
    current_time = now or datetime.now().astimezone()
    project_entries = summarize_projects_from_details(details, pricing)[: max(limit, 0)]
    drilldowns: list[ProjectDrilldown] = []
    for entry in project_entries:
        project_details = filter_details_by_project(details, entry.name)
        summary = summarize_details(entry.name, project_details, pricing)
        insights = summarize_insights_from_details(project_details, pricing=pricing, month=summary, now=current_time)
        drilldowns.append(
            ProjectDrilldown(
                name=entry.name,
                summary=summary,
                top_sessions=summarize_top_sessions_from_details(project_details, pricing, limit=5),
                history=summarize_history_from_details(project_details, pricing, limit=5),
                daily_points=summarize_daily_from_details(project_details, days=max(days, 1), now=current_time, pricing=pricing),
                activity_heatmap=summarize_activity_heatmap_from_details(project_details, timezone=current_time.tzinfo),
                insights=insights,
                takeaways=summarize_takeaways(summary=summary, insights=insights, max_items=3, scope_label=entry.name),
                file_impact=summarize_files_from_details(project_details, limit=10),
            )
        )
    return drilldowns


def summarize_takeaways(
    *,
    summary: TimeSummary,
    insights: InsightReport,
    comparison: CompareReport | None = None,
    costs: CostSummary | None = None,
    file_impact: list[FileImpactEntry] | None = None,
    behavior: BehaviorSummary | None = None,
    branches: BranchSummary | None = None,
    max_items: int = 4,
    scope_label: str | None = None,
) -> list[str]:
    takeaways: list[str] = []
    if comparison and comparison.total_tokens_delta_pct is not None:
        direction = "up" if comparison.total_tokens_delta_pct >= 0 else "down"
        takeaways.append(
            f"Usage moved {direction} {abs(comparison.total_tokens_delta_pct):.1f}% versus {comparison.previous.label}."
        )
    if file_impact:
        edited_files = len(file_impact)
        added_lines = sum(entry.insertions for entry in file_impact)
        removed_lines = sum(entry.deletions for entry in file_impact)
        takeaways.append(
            f"File work touched {edited_files} file{'s' if edited_files != 1 else ''}, adding {added_lines:,} lines and removing {removed_lines:,} lines."
        )
    if summary.project_concentration_top1_pct is not None and summary.project_concentration_top1_pct >= 0.6:
        takeaways.append(
            f"Work is concentrated: the top project accounts for {_fmt_ratio_pct(summary.project_concentration_top1_pct)} of tokens."
        )
    if summary.longest_active_streak_days >= 3:
        takeaways.append(f"Active streak reached {summary.longest_active_streak_days} days.")
    if summary.average_tokens_per_request >= 25_000:
        takeaways.append(f"Average request size is high at {summary.average_tokens_per_request:,.0f} tokens.")
    if summary.cache_ratio is not None and summary.cache_ratio < 0.25:
        takeaways.append(f"Cache reuse is low at {_fmt_ratio_pct(summary.cache_ratio)}.")
    if costs and costs.projected_monthly_cost_usd > summary.estimated_cost_usd and summary.estimated_cost_usd > 0:
        takeaways.append(f"Current pace projects to ${costs.projected_monthly_cost_usd:.2f} for the month.")
    if insights.anomalies:
        takeaways.append(insights.anomalies[0] + ".")
    behavior_lines = summarize_behavior_takeaways(behavior)
    branch_lines = summarize_branch_takeaways(branches)
    preferred = _interleave(behavior_lines, branch_lines)
    if preferred:
        # Measured facts about what was actually done outrank the heuristic cost
        # advice, so they take the tail of the list and the advice is trimmed to
        # whatever room is left. The room is clamped at zero because when the
        # measured lines outnumber the slots on their own, a negative bound would
        # slice from the end and hand the whole budget back to the advice, dropping
        # exactly the lines this is meant to promote.
        room = max(max_items, 1) - len(preferred)
        takeaways = takeaways[: max(room, 0)] + preferred
    if not takeaways:
        label = scope_label or summary.label
        takeaways.append(f"{label.title()} usage looks balanced with no obvious warning patterns.")
    return takeaways[: max(max_items, 1)]


def _interleave(*groups: list[str]) -> list[str]:
    """Round-robin the groups so a long first group cannot crowd out the rest.

    Tool behavior and branch facts are both measured, and either can be the more
    interesting one on a given day. Appending them in order would let whichever
    came first fill every slot, so they alternate instead and both stay visible.
    """
    result: list[str] = []
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                result.append(group[index])
    return result


def summarize_badges(
    *,
    summary: TimeSummary,
    daily_points: list[DailyPoint],
    activity_heatmap: list[HeatmapCell],
) -> list[DashboardBadge]:
    badges: list[DashboardBadge] = []
    if summary.top_model:
        badges.append(DashboardBadge(label="Top model", value=summary.top_model))
    busiest_day = max(daily_points, key=lambda point: point.total_tokens, default=None)
    if busiest_day and busiest_day.total_tokens > 0:
        badges.append(DashboardBadge(label="Busiest day", value=f"{busiest_day.day[5:]}"))
    peak_cell = max(activity_heatmap, key=lambda cell: cell.total_tokens, default=None)
    if peak_cell and peak_cell.total_tokens > 0:
        weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][peak_cell.weekday]
        badges.append(DashboardBadge(label="Peak hour", value=f"{weekday} {peak_cell.hour:02d}:00"))
    if summary.longest_active_streak_days > 0:
        badges.append(DashboardBadge(label="Streak", value=f"{summary.longest_active_streak_days} day{'s' if summary.longest_active_streak_days != 1 else ''}"))
    return badges[:4]


def summarize_expensive_session(
    details: list[SessionDetails],
    pricing: PricingConfig | None = None,
) -> SessionSpotlight | None:
    pricing = pricing or PricingConfig()
    if not details:
        return None
    most_expensive = max(details, key=lambda detail: estimate_detail_cost(detail, pricing))
    return SessionSpotlight(
        project_name=most_expensive.session.project_name,
        model=most_expensive.session.model,
        total_tokens=most_expensive.effective_total_tokens(),
        requests=most_expensive.request_count,
        estimated_cost_usd=estimate_detail_cost(most_expensive, pricing),
    )


def summarize_work_rhythm(
    daily_points: list[DailyPoint],
    activity_heatmap: list[HeatmapCell],
) -> WorkRhythm:
    active_days = [point for point in daily_points if point.total_tokens > 0]
    if not active_days or not activity_heatmap:
        return WorkRhythm(
            headline="Still learning your rhythm.",
            detail="Use Codex across a few days and times to unlock a clearer work pattern summary.",
            peak_day=None,
            peak_hour=None,
        )
    weekday_totals: dict[int, int] = defaultdict(int)
    hour_totals: dict[int, int] = defaultdict(int)
    active_weekdays = set()
    for cell in activity_heatmap:
        if cell.total_tokens <= 0:
            continue
        weekday_totals[cell.weekday] += cell.total_tokens
        hour_totals[cell.hour] += cell.total_tokens
        active_weekdays.add(cell.weekday)
    peak_weekday = max(weekday_totals, key=weekday_totals.get, default=None)
    peak_hour = max(hour_totals, key=hour_totals.get, default=None)
    weekday_name = (
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][peak_weekday]
        if peak_weekday is not None
        else None
    )
    hour_label = _fmt_hour(peak_hour) if peak_hour is not None else None
    if len(active_weekdays) <= 2:
        cadence = "clustered into a few focused days"
    elif len(active_weekdays) >= 5:
        cadence = "spread across most of the week"
    else:
        cadence = "centered on a mid-week rhythm"
    if weekday_name and hour_label:
        detail = f"Your strongest weekday is {weekday_name}, and the busiest hour overall lands around {hour_label}."
    elif weekday_name:
        detail = f"Your strongest weekday is {weekday_name}."
    else:
        detail = "Use Codex across a few more sessions to unlock a clearer work pattern summary."
    return WorkRhythm(
        headline=f"Your work is {cadence}.",
        detail=detail,
        peak_day=weekday_name,
        peak_hour=hour_label,
    )


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


def summarize_files_from_details(
    details: list[SessionDetails],
    limit: int = 10,
) -> list[FileImpactEntry]:
    grouped: dict[str, dict] = defaultdict(
        lambda: {
            "edits": 0,
            "sessions": set(),
            "insertions": 0,
            "deletions": 0,
            "created": 0,
            "updated": 0,
            "deleted": 0,
        }
    )
    for detail in details:
        for edit in detail.file_edits:
            bucket = grouped[edit.path]
            bucket["edits"] += 1
            bucket["sessions"].add(detail.session.session_id)
            bucket["insertions"] += edit.insertions
            bucket["deletions"] += edit.deletions
            bucket[edit.action] += 1
    entries = [
        FileImpactEntry(
            path=path,
            edits=bucket["edits"],
            sessions=len(bucket["sessions"]),
            insertions=bucket["insertions"],
            deletions=bucket["deletions"],
            created=bucket["created"],
            updated=bucket["updated"],
            deleted=bucket["deleted"],
        )
        for path, bucket in grouped.items()
    ]
    entries.sort(key=lambda entry: (-entry.edits, -(entry.insertions + entry.deletions), entry.path))
    return entries[: max(limit, 0)]


def summarize_behavior_from_details(
    details: list[SessionDetails],
    *,
    tool_limit: int = 12,
) -> BehaviorSummary | None:
    """Aggregate what the agents actually did, independently of what they cost.

    Repeated calls are counted per session, because the same command run twice in one
    session is redundant work, while the same command run once a week for a month is a
    routine. ``supported`` is false when nothing in scope reported tool calls, so an
    empty panel can distinguish "no tool use" from "this source does not record tool use".
    """
    all_calls = [call for detail in details for call in detail.tool_calls]
    if not all_calls:
        return BehaviorSummary(
            total_calls=0,
            error_calls=0,
            repeated_calls=0,
            sessions_with_calls=0,
            abandoned_turns=sum(detail.abandoned_turns for detail in details),
            read_calls=0,
            edit_calls=0,
            categories=[],
            tools=[],
            supported=False,
        )

    per_session: dict[str, Counter[str]] = defaultdict(Counter)
    repeated = 0
    repeated_duration_ms = 0
    total_duration_ms = 0
    timed_calls = 0
    for detail in details:
        seen = per_session[detail.session.session_id]
        for call in detail.tool_calls:
            seen[call.fingerprint] += 1
            if seen[call.fingerprint] > 1:
                repeated += 1
                if call.duration_ms is not None:
                    repeated_duration_ms += call.duration_ms
            if call.duration_ms is not None:
                total_duration_ms += call.duration_ms
                timed_calls += 1

    recovered_errors = 0
    recovered_tool_errors: Counter[str] = Counter()
    for detail in details:
        pending: dict[str, int] = {}
        for call in detail.tool_calls:
            if call.is_error:
                pending[call.fingerprint] = pending.get(call.fingerprint, 0) + 1
            elif call.fingerprint in pending:
                recovered = pending.pop(call.fingerprint)
                recovered_errors += recovered
                recovered_tool_errors[call.name] += recovered

    category_calls: Counter[str] = Counter()
    category_errors: Counter[str] = Counter()
    tool_names: Counter[str] = Counter()
    tool_errors: Counter[str] = Counter()
    tool_durations: Counter[str] = Counter()
    tool_categories: dict[str, str] = {}

    for call in all_calls:
        category_calls[call.category] += 1
        tool_names[call.name] += 1
        tool_categories.setdefault(call.name, call.category)
        if call.is_error:
            category_errors[call.category] += 1
            tool_errors[call.name] += 1
        if call.duration_ms is not None:
            tool_durations[call.name] += call.duration_ms

    categories = [
        ToolCategoryEntry(
            category=key,
            label=TOOL_CATEGORY_LABELS.get(key, key.title()),
            calls=category_calls[key],
            errors=category_errors[key],
        )
        for key in TOOL_CATEGORY_ORDER
        if category_calls[key]
    ]
    ranked_names = tool_names.most_common(max(tool_limit, 0))
    tools = [
        ToolUsageEntry(
            name=name,
            category=tool_categories.get(name, TOOL_CATEGORY_OTHER),
            calls=count,
            errors=tool_errors[name],
            total_duration_ms=tool_durations[name],
            recovered_errors=recovered_tool_errors[name],
        )
        for name, count in ranked_names
    ]
    return BehaviorSummary(
        total_calls=len(all_calls),
        error_calls=sum(1 for call in all_calls if call.is_error),
        repeated_calls=repeated,
        sessions_with_calls=sum(1 for counter in per_session.values() if counter),
        abandoned_turns=sum(detail.abandoned_turns for detail in details),
        read_calls=category_calls[TOOL_CATEGORY_READ],
        edit_calls=category_calls[TOOL_CATEGORY_EDIT],
        categories=categories,
        tools=tools,
        supported=True,
        repeated_duration_ms=repeated_duration_ms,
        total_duration_ms=total_duration_ms,
        timed_calls=timed_calls,
        recovered_errors=recovered_errors,
    )


def summarize_behavior_takeaways(behavior: BehaviorSummary | None) -> list[str]:
    if behavior is None or not behavior.supported or not behavior.total_calls:
        return []
    lines: list[str] = []
    if behavior.error_rate is not None and behavior.error_rate >= 0.05:
        lines.append(
            f"{behavior.error_rate * 100:.0f}% of tool calls failed "
            f"({behavior.error_calls:,} of {behavior.total_calls:,})."
        )
    if behavior.repeat_rate is not None and behavior.repeat_rate >= 0.1:
        lines.append(
            f"{behavior.repeated_calls:,} calls repeated work already done in the same "
            f"session ({behavior.repeat_rate * 100:.0f}% of all calls)."
        )
    if behavior.repeat_time_rate is not None and behavior.repeat_time_rate >= 0.2:
        lines.append(
            f"Repeated calls consumed {behavior.repeat_time_rate * 100:.0f}% of tool time "
            f"({_fmt_tool_time(behavior.repeated_duration_ms)} of "
            f"{_fmt_tool_time(behavior.total_duration_ms)})."
        )
    if behavior.error_calls >= 3 and behavior.error_recovery_rate is not None:
        recovered = behavior.error_recovery_rate
        if recovered < 0.5:
            unrecovered_noun = "call" if behavior.unrecovered_errors == 1 else "calls"
            lines.append(
                f"Only {recovered * 100:.0f}% of the {behavior.error_calls:,} tool failures were "
                f"retried to success in-session; {behavior.unrecovered_errors:,} failed {unrecovered_noun} "
                "were never resolved."
            )
        elif recovered >= 0.7:
            lines.append(
                f"Resolved {behavior.recovered_errors:,} of {behavior.error_calls:,} tool failures "
                "in-session by retrying."
            )
    if behavior.read_write_ratio is not None and behavior.read_write_ratio >= 8:
        lines.append(
            f"Read-heavy work: {behavior.read_calls:,} reads against "
            f"{behavior.edit_calls:,} edits."
        )
    if behavior.abandoned_turns:
        lines.append(
            f"{behavior.abandoned_turns} turn{'s were' if behavior.abandoned_turns != 1 else ' was'} "
            "abandoned before finishing."
        )
    return lines


def _fmt_tool_time(ms: int) -> str:
    if ms < 60_000:
        return f"{ms / 1000:.0f}s"
    minutes = ms / 60_000
    if minutes < 60:
        return f"{minutes:.0f}m"
    return f"{minutes / 60:.1f}h"


def _fmt_ratio_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.0f}%"


def _fmt_hour(hour: int) -> str:
    if hour == 0:
        return "12 AM"
    if hour < 12:
        return f"{hour} AM"
    if hour == 12:
        return "12 PM"
    return f"{hour - 12} PM"


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
