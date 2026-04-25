from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    created_at: datetime
    updated_at: datetime
    cwd: str
    model: str | None
    model_provider: str
    tokens_used: int
    rollout_path: Path
    git_branch: str | None
    git_origin_url: str | None

    @property
    def project_name(self) -> str:
        cwd_path = Path(self.cwd)
        return cwd_path.name or self.cwd

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["updated_at"] = self.updated_at.isoformat()
        payload["rollout_path"] = str(self.rollout_path)
        payload["project_name"] = self.project_name
        return payload


@dataclass(frozen=True)
class SessionDetails:
    session: SessionRecord
    request_count: int
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_output_tokens: int | None
    total_tokens_from_rollout: int | None
    started_at: datetime | None

    def effective_total_tokens(self) -> int:
        if self.total_tokens_from_rollout is not None:
            return self.total_tokens_from_rollout
        return self.session.tokens_used

    def duration_minutes(self) -> float:
        started = self.started_at or self.session.created_at
        seconds = max((self.session.updated_at - started).total_seconds(), 0.0)
        return seconds / 60.0

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "session": self.session.to_dict(),
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "total_tokens_from_rollout": self.total_tokens_from_rollout,
            "effective_total_tokens": self.effective_total_tokens(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }
        return payload


@dataclass(frozen=True)
class TimeSummary:
    label: str
    sessions: int
    requests: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    top_model: str | None
    average_tokens_per_request: float
    cache_ratio: float | None
    largest_session_tokens: int
    requests_per_session: float
    median_tokens_per_session: float
    median_requests_per_session: float
    average_session_duration_minutes: float
    median_session_duration_minutes: float
    tokens_per_minute: float
    project_concentration_top1_pct: float | None
    project_concentration_top3_pct: float | None
    longest_active_streak_days: int
    model_switching_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BreakdownEntry:
    name: str
    sessions: int
    requests: int
    total_tokens: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoryEntry:
    session_id: str
    project_name: str
    model: str | None
    updated_at: datetime
    total_tokens: int
    requests: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["updated_at"] = self.updated_at.isoformat()
        return payload


@dataclass(frozen=True)
class CostSummary:
    today_cost_usd: float
    week_cost_usd: float
    month_cost_usd: float
    projected_monthly_cost_usd: float
    highest_session_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InsightReport:
    average_tokens_per_request: float
    cache_ratio: float | None
    large_session_count: int
    possible_savings_usd: float
    largest_session_tokens: int
    suggestion: str
    anomalies: list[str]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DailyPoint:
    day: str
    total_tokens: int
    requests: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HeatmapCell:
    weekday: int
    hour: int
    session_count: int
    total_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CompareReport:
    current: TimeSummary
    previous: TimeSummary
    total_tokens_delta: int
    total_tokens_delta_pct: float | None
    requests_delta: int
    cost_delta_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current.to_dict(),
            "previous": self.previous.to_dict(),
            "total_tokens_delta": self.total_tokens_delta,
            "total_tokens_delta_pct": self.total_tokens_delta_pct,
            "requests_delta": self.requests_delta,
            "cost_delta_usd": self.cost_delta_usd,
        }


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WatchAlert:
    severity: str
    name: str
    detail: str
    is_new: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopEntry:
    session_id: str
    project_name: str
    model: str | None
    total_tokens: int
    requests: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DashboardBadge:
    label: str
    value: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SessionSpotlight:
    project_name: str
    model: str | None
    total_tokens: int
    requests: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkRhythm:
    headline: str
    detail: str
    peak_day: str | None
    peak_hour: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReportData:
    period: str
    project_name: str | None
    summary: TimeSummary
    comparison: CompareReport
    projects: list[BreakdownEntry]
    top_sessions: list[TopEntry]
    costs: CostSummary
    insights: InsightReport
    activity_heatmap: list[HeatmapCell]

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "project_name": self.project_name,
            "summary": self.summary.to_dict(),
            "comparison": self.comparison.to_dict(),
            "projects": [entry.to_dict() for entry in self.projects],
            "top_sessions": [entry.to_dict() for entry in self.top_sessions],
            "costs": self.costs.to_dict(),
            "insights": self.insights.to_dict(),
            "activity_heatmap": [cell.to_dict() for cell in self.activity_heatmap],
        }


@dataclass(frozen=True)
class DashboardWindow:
    key: str
    label: str
    description: str
    comparison_label: str
    summary: TimeSummary
    comparison: CompareReport
    projects: list[BreakdownEntry]
    top_sessions: list[TopEntry]
    history: list[HistoryEntry]
    daily_points: list[DailyPoint]
    costs: CostSummary
    insights: InsightReport
    activity_heatmap: list[HeatmapCell]
    takeaways: list[str]
    badges: list[DashboardBadge]
    expensive_session: SessionSpotlight | None
    work_rhythm: WorkRhythm
    project_drilldowns: list["ProjectDrilldown"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "comparison_label": self.comparison_label,
            "summary": self.summary.to_dict(),
            "comparison": self.comparison.to_dict(),
            "projects": [entry.to_dict() for entry in self.projects],
            "top_sessions": [entry.to_dict() for entry in self.top_sessions],
            "history": [entry.to_dict() for entry in self.history],
            "daily_points": [point.to_dict() for point in self.daily_points],
            "costs": self.costs.to_dict(),
            "insights": self.insights.to_dict(),
            "activity_heatmap": [cell.to_dict() for cell in self.activity_heatmap],
            "takeaways": self.takeaways,
            "badges": [badge.to_dict() for badge in self.badges],
            "expensive_session": self.expensive_session.to_dict() if self.expensive_session else None,
            "work_rhythm": self.work_rhythm.to_dict(),
            "project_drilldowns": [drilldown.to_dict() for drilldown in self.project_drilldowns],
        }


@dataclass(frozen=True)
class ProjectDrilldown:
    name: str
    summary: TimeSummary
    top_sessions: list[TopEntry]
    history: list[HistoryEntry]
    daily_points: list[DailyPoint]
    activity_heatmap: list[HeatmapCell]
    insights: InsightReport
    takeaways: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "summary": self.summary.to_dict(),
            "top_sessions": [entry.to_dict() for entry in self.top_sessions],
            "history": [entry.to_dict() for entry in self.history],
            "daily_points": [point.to_dict() for point in self.daily_points],
            "activity_heatmap": [cell.to_dict() for cell in self.activity_heatmap],
            "insights": self.insights.to_dict(),
            "takeaways": self.takeaways,
        }


@dataclass(frozen=True)
class DashboardData:
    generated_at: datetime
    windows: list[DashboardWindow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "windows": [window.to_dict() for window in self.windows],
        }


@dataclass(frozen=True)
class DisplayConfigView:
    color: str
    history_limit: int
    compare_days: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConfigView:
    config_path: str
    exists: bool
    pricing_default_usd_per_1k_tokens: float
    pricing_model_overrides: dict[str, float]
    display: DisplayConfigView

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "exists": self.exists,
            "pricing_default_usd_per_1k_tokens": self.pricing_default_usd_per_1k_tokens,
            "pricing_model_overrides": self.pricing_model_overrides,
            "display": self.display.to_dict(),
        }


@dataclass(frozen=True)
class ImportSummary:
    files_read: int
    sessions_loaded: int
    duplicates_removed: int
    merged_sessions: int
    oldest_session_at: str | None
    newest_session_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
