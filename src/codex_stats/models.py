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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
