from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SOURCE = "codex"


TOOL_STATUS_COMPLETED = "completed"
TOOL_STATUS_ERROR = "error"
TOOL_STATUS_UNKNOWN = "unknown"

TOOL_CATEGORY_READ = "read"
TOOL_CATEGORY_EDIT = "edit"
TOOL_CATEGORY_EXEC = "exec"
TOOL_CATEGORY_SEARCH = "search"
TOOL_CATEGORY_WEB = "web"
TOOL_CATEGORY_AGENT = "agent"
TOOL_CATEGORY_PLAN = "plan"
TOOL_CATEGORY_OTHER = "other"

TOOL_CATEGORY_ORDER: tuple[str, ...] = (
    TOOL_CATEGORY_READ,
    TOOL_CATEGORY_EDIT,
    TOOL_CATEGORY_EXEC,
    TOOL_CATEGORY_SEARCH,
    TOOL_CATEGORY_WEB,
    TOOL_CATEGORY_AGENT,
    TOOL_CATEGORY_PLAN,
    TOOL_CATEGORY_OTHER,
)

TOOL_CATEGORY_LABELS: dict[str, str] = {
    TOOL_CATEGORY_READ: "Read",
    TOOL_CATEGORY_EDIT: "Edit",
    TOOL_CATEGORY_EXEC: "Execute",
    TOOL_CATEGORY_SEARCH: "Search",
    TOOL_CATEGORY_WEB: "Web",
    TOOL_CATEGORY_AGENT: "Subagent",
    TOOL_CATEGORY_PLAN: "Plan",
    TOOL_CATEGORY_OTHER: "Other",
}


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
    source: str = DEFAULT_SOURCE

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
class FileEdit:
    path: str
    action: str
    insertions: int
    deletions: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CACHED_WITHIN_INPUT = "cached_within_input"
CACHED_SEPARATE = "cached_separate"


@dataclass(frozen=True)
class TokenSplit:
    fresh_input: int = 0
    cached_read: int = 0
    cache_write: int = 0
    output: int = 0

    @property
    def total(self) -> int:
        return self.fresh_input + self.cached_read + self.cache_write + self.output

    @property
    def input_total(self) -> int:
        return self.fresh_input + self.cached_read

    def cache_ratio(self) -> float | None:
        if not self.input_total:
            return None
        return self.cached_read / self.input_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "fresh_input": self.fresh_input,
            "cached_read": self.cached_read,
            "cache_write": self.cache_write,
            "output": self.output,
            "total": self.total,
        }


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation recorded by a coding agent.

    ``name`` is the raw name the CLI used, ``category`` is the normalized bucket shared
    across every source, and ``fingerprint`` identifies the call's arguments so repeated
    invocations of the same work can be detected inside a session.
    """

    name: str
    category: str
    fingerprint: str
    status: str = TOOL_STATUS_UNKNOWN
    duration_ms: int | None = None

    @property
    def is_error(self) -> bool:
        return self.status == TOOL_STATUS_ERROR

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "fingerprint": self.fingerprint,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }


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
    recorded_cost_usd: float | None = None
    file_edits: tuple[FileEdit, ...] = ()
    cache_write_tokens: int | None = None
    token_accounting: str = CACHED_WITHIN_INPUT
    tool_calls: tuple[ToolCall, ...] = ()
    abandoned_turns: int = 0
    # Hermes counts context rewrites that failed to shrink a session ("compression
    # was ineffective"); when the source records the count, sessions that paid for
    # a rewrite and got nothing are visible rather than invisible.
    compression_ineffective_count: int | None = None
    # OpenCode records file-change totals on a session where it did not record the
    # individual edits: (files, additions, deletions, diffs). Set only when the
    # database has non-zero figures, so sources that report nothing stay "not
    # recorded" instead of being read as "no files touched".
    opencode_summary: tuple[int, int, int, int] | None = None

    def fresh_input_tokens(self) -> int:
        raw = self.input_tokens or 0
        if self.token_accounting == CACHED_WITHIN_INPUT:
            return max(raw - (self.cached_input_tokens or 0), 0)
        return raw

    def cached_read_tokens(self) -> int:
        return self.cached_input_tokens or 0

    def cache_creation_tokens(self) -> int:
        return self.cache_write_tokens or 0

    def billable_output_tokens(self) -> int:
        output = self.output_tokens or 0
        if self.token_accounting == CACHED_WITHIN_INPUT:
            return output
        return output + (self.reasoning_output_tokens or 0)

    def token_split(self) -> TokenSplit:
        return TokenSplit(
            fresh_input=self.fresh_input_tokens(),
            cached_read=self.cached_read_tokens(),
            cache_write=self.cache_creation_tokens(),
            output=self.billable_output_tokens(),
        )

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
            "cache_write_tokens": self.cache_write_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "token_accounting": self.token_accounting,
            "token_split": self.token_split().to_dict(),
            "total_tokens_from_rollout": self.total_tokens_from_rollout,
            "effective_total_tokens": self.effective_total_tokens(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "recorded_cost_usd": self.recorded_cost_usd,
            "file_edits": [edit.to_dict() for edit in self.file_edits],
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "abandoned_turns": self.abandoned_turns,
            "compression_ineffective_count": self.compression_ineffective_count,
            "opencode_summary": self.opencode_summary,
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
    fresh_input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    unrated_sessions: int = 0

    def token_split(self) -> TokenSplit:
        return TokenSplit(
            fresh_input=self.fresh_input_tokens,
            cached_read=self.cache_read_tokens,
            cache_write=self.cache_write_tokens,
            output=self.output_tokens,
        )

    @property
    def reasoning_ratio(self) -> float | None:
        """Share of the window's tokens that were reasoning tokens.

        Reasoning tokens are billed as output and are added on top of the plain
        output figure at ingest, so they are a genuine fraction of the total rather
        than a subset of it. None when nothing in scope recorded reasoning, which is
        the normal case for the providers that do not expose a separate figure.
        """
        if not self.reasoning_output_tokens or not self.total_tokens:
            return None
        return self.reasoning_output_tokens / self.total_tokens

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
class BranchActivity:
    """Tokens and spend for one branch of one repository.

    A branch name is only unique within its repository, so ``name`` alone is not
    enough to identify a workstream: ``feature/login`` exists independently in
    several checkouts. Every grouping carries ``project_name`` for that reason.
    """

    name: str
    project_name: str
    sessions: int
    requests: int
    total_tokens: int
    estimated_cost_usd: float
    first_at: datetime
    last_at: datetime
    idle_days: int

    @property
    def label(self) -> str:
        return f"{self.project_name} / {self.name}"

    @property
    def tokens_per_session(self) -> float:
        return self.total_tokens / self.sessions if self.sessions else 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["first_at"] = self.first_at.isoformat()
        payload["last_at"] = self.last_at.isoformat()
        payload["label"] = self.label
        return payload


@dataclass(frozen=True)
class BranchSummary:
    """Per-branch spend, split into active work and branches that went quiet.

    ``supported`` is false when no session in scope carried a branch, which is what
    lets an empty panel say "this tool does not record branches" instead of implying
    the user worked on no branches at all.
    """

    branches: list[BranchActivity]
    tracked_sessions: int
    total_sessions: int
    idle_branches: list[BranchActivity]
    supported: bool = True

    @property
    def untracked_sessions(self) -> int:
        return max(self.total_sessions - self.tracked_sessions, 0)

    @property
    def idle_cost_usd(self) -> float:
        return round(sum(branch.estimated_cost_usd for branch in self.idle_branches), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branches": [branch.to_dict() for branch in self.branches],
            "tracked_sessions": self.tracked_sessions,
            "total_sessions": self.total_sessions,
            "untracked_sessions": self.untracked_sessions,
            "idle_branches": [branch.to_dict() for branch in self.idle_branches],
            "idle_cost_usd": self.idle_cost_usd,
            "supported": self.supported,
        }


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
class SessionDrilldown:
    """One session, opened the way a project drilldown opens a project.

    Top sessions answer which session cost the most; this is the rest of that
    answer — the token split, the tools the session called and how often each one
    failed, and the files it edited, when the source records them. Sources that
    keep neither tools nor files legitimately show empty lists here.
    """

    session_id: str
    project_name: str
    branch: str | None
    model: str | None
    model_provider: str | None
    created_at: datetime
    updated_at: datetime
    requests: int
    total_tokens: int
    estimated_cost_usd: float
    token_split: TokenSplit
    tools: list[ToolUsageEntry] = field(default_factory=list, repr=False)
    file_edits: list[FileEdit] = field(default_factory=list, repr=False)
    compression_ineffective_count: int | None = None
    opencode_summary: tuple[int, int, int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        payload["updated_at"] = self.updated_at.isoformat()
        payload["token_split"] = self.token_split.to_dict()
        return payload


@dataclass(frozen=True)
class ToolUsageEntry:
    name: str
    category: str
    calls: int
    errors: int
    total_duration_ms: int
    recovered_errors: int = 0

    @property
    def error_rate(self) -> float | None:
        if not self.calls:
            return None
        return self.errors / self.calls

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolCategoryEntry:
    category: str
    label: str
    calls: int
    errors: int

    @property
    def share(self) -> float:
        return self.calls

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BehaviorSummary:
    """What the agents actually did, as opposed to what they cost.

    ``supported`` is false when no source in scope reported any tool calls, so an empty
    panel can say "not tracked here" instead of implying the agent made no tool calls.
    """

    total_calls: int
    error_calls: int
    repeated_calls: int
    sessions_with_calls: int
    abandoned_turns: int
    read_calls: int
    edit_calls: int
    categories: list[ToolCategoryEntry]
    tools: list[ToolUsageEntry]
    supported: bool = True
    repeated_duration_ms: int = 0
    total_duration_ms: int = 0
    timed_calls: int = 0
    recovered_errors: int = 0

    @property
    def error_rate(self) -> float | None:
        if not self.total_calls:
            return None
        return self.error_calls / self.total_calls

    @property
    def repeat_rate(self) -> float | None:
        if not self.total_calls:
            return None
        return self.repeated_calls / self.total_calls

    @property
    def repeat_time_rate(self) -> float | None:
        if not self.total_duration_ms:
            return None
        return self.repeated_duration_ms / self.total_duration_ms

    @property
    def error_recovery_rate(self) -> float | None:
        if not self.error_calls:
            return None
        return self.recovered_errors / self.error_calls

    @property
    def unrecovered_errors(self) -> int:
        return self.error_calls - self.recovered_errors

    @property
    def read_write_ratio(self) -> float | None:
        if not self.edit_calls:
            return None
        return self.read_calls / self.edit_calls

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "error_calls": self.error_calls,
            "repeated_calls": self.repeated_calls,
            "sessions_with_calls": self.sessions_with_calls,
            "abandoned_turns": self.abandoned_turns,
            "read_calls": self.read_calls,
            "edit_calls": self.edit_calls,
            "categories": [entry.to_dict() for entry in self.categories],
            "tools": [entry.to_dict() for entry in self.tools],
            "supported": self.supported,
            "repeated_duration_ms": self.repeated_duration_ms,
            "total_duration_ms": self.total_duration_ms,
            "timed_calls": self.timed_calls,
            "recovered_errors": self.recovered_errors,
        }


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
    tool_breakdown: list[BreakdownEntry] | None = None
    tool_daily_points: list["ToolDailyPoint"] | None = None
    file_impact: list["FileImpactEntry"] = field(default_factory=list, repr=False)
    behavior: "BehaviorSummary | None" = None
    branches: "BranchSummary | None" = None
    providers: list[BreakdownEntry] = field(default_factory=list, repr=False)
    efficiency: "EfficiencySummary | None" = None
    tool_efficiency: list["ToolEfficiency"] = field(default_factory=list, repr=False)

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
            "tool_breakdown": [entry.to_dict() for entry in self.tool_breakdown] if self.tool_breakdown else None,
            "tool_daily_points": [point.to_dict() for point in self.tool_daily_points] if self.tool_daily_points else None,
            "file_impact": [entry.to_dict() for entry in self.file_impact],
            "behavior": self.behavior.to_dict() if self.behavior else None,
            "branches": self.branches.to_dict() if self.branches else None,
            "providers": [entry.to_dict() for entry in self.providers],
            "efficiency": self.efficiency.to_dict() if self.efficiency else None,
            "tool_efficiency": [entry.to_dict() for entry in self.tool_efficiency],
        }


@dataclass(frozen=True)
class ToolDailyPoint:
    day: str
    source: str
    total_tokens: int
    estimated_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "source": self.source,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
        }


@dataclass(frozen=True)
class ChurnEntry:
    """One file's edit history across every project in the window.

    File impact is otherwise only visible from inside a single project's
    drilldown, which makes it impossible to answer "which files do I keep
    rewriting no matter which repo I am in". Ranking by how many sessions
    touched a file surfaces the ones that resist convergence; a negative
    ``net_lines`` is the stronger signal, since it means the window finished
    smaller than it started.
    """

    path: str
    sessions: int
    edits: int
    insertions: int
    deletions: int

    @property
    def net_lines(self) -> int:
        return self.insertions - self.deletions

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["net_lines"] = self.net_lines
        return payload


@dataclass(frozen=True)
class EfficiencySummary:
    """What the window's spend actually bought.

    Every other panel answers "how much" or "where". This one answers "for what",
    by joining cost to the file edits recorded in the same sessions. That join is
    only meaningful for sources that record edits at all, so ``tracked`` carries
    whether the window has that data and every derived figure is None without it,
    rather than reporting a division by zero as though it were a bad result.
    """

    tracked: bool
    untracked_sources: tuple[str, ...]
    tracked_cost_usd: float
    untracked_cost_usd: float
    read_only_cost_usd: float
    editing_sessions: int
    read_only_sessions: int
    lines_changed: int
    insertions: int
    deletions: int
    files_touched: int
    cost_per_1k_lines: float | None
    cost_per_file: float | None
    cost_per_editing_session: float | None
    rework_ratio: float | None
    churn_files: int
    hotspots: list[ChurnEntry] = field(default_factory=list, repr=False)

    @property
    def read_only_cost_share(self) -> float | None:
        """Share of tracked spend that went to sessions which changed nothing.

        Only meaningful when a source is actually recording edits, so it stays None
        otherwise instead of reporting that every session was read-only.
        """
        if not self.tracked or self.tracked_cost_usd <= 0:
            return None
        return self.read_only_cost_usd / self.tracked_cost_usd

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["read_only_cost_share"] = self.read_only_cost_share
        # Nested asdict would drop ChurnEntry.net_lines, which is a derived
        # property rather than a field, so the list is serialized explicitly.
        payload["hotspots"] = [entry.to_dict() for entry in self.hotspots]
        return payload


@dataclass(frozen=True)
class ToolEfficiency:
    """One tool's spend measured against the work it recorded.

    ``tracks_file_edits`` is False for the tools whose databases record tokens and
    cost but nothing about files. Those rows still show their spend, so the
    comparison stays honest, but they carry no per-line figure and must not be
    ranked as if they were expensive.
    """

    source: str
    label: str
    tracks_file_edits: bool
    sessions: int
    estimated_cost_usd: float
    lines_changed: int
    files_touched: int
    cost_per_1k_lines: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FileImpactEntry:
    path: str
    edits: int
    sessions: int
    insertions: int
    deletions: int
    created: int
    updated: int
    deleted: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    file_impact: list[FileImpactEntry] = field(default_factory=list, repr=False)
    sessions: list[SessionDrilldown] = field(default_factory=list, repr=False)

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
            "file_impact": [entry.to_dict() for entry in self.file_impact],
            "sessions": [session.to_dict() for session in self.sessions],
        }


@dataclass(frozen=True)
class DashboardScope:
    key: str
    label: str
    description: str
    source: str
    windows: list[DashboardWindow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "source": self.source,
            "windows": [window.to_dict() for window in self.windows],
        }


@dataclass(frozen=True)
class DashboardData:
    generated_at: datetime
    windows: list[DashboardWindow] = field(default_factory=list, repr=False)
    scopes: list[DashboardScope] = field(default_factory=list)
    coverage_note: str | None = None
    # Set when a user's config.toml could not be read. The run continues on the
    # built-in rate table, so the page has to say that the prices below it are not
    # the ones that file asked for.
    config_error: str | None = None
    # Set when the user configured a monthly budget and the calendar-month spend
    # has reached the warn threshold. Kept alongside the other page-level notices:
    # it qualifies every number the same way the coverage note does, once, up top.
    budget_note: str | None = None

    def __post_init__(self) -> None:
        if not self.scopes and self.windows:
            object.__setattr__(
                self,
                "scopes",
                [
                    DashboardScope(
                        key="overview",
                        label="Overview",
                        description="All tracked tools combined.",
                        source="overview",
                        windows=list(self.windows),
                    )
                ],
            )
        elif self.scopes and not self.windows:
            object.__setattr__(
                self,
                "windows",
                [window for scope in self.scopes for window in scope.windows],
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "scopes": [scope.to_dict() for scope in self.scopes],
            "coverage_note": self.coverage_note,
            "config_error": self.config_error,
            "budget_note": self.budget_note,
        }
