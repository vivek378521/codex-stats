from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILENAME = "last_snapshot.json"


@dataclass(frozen=True)
class Snapshot:
    generated_at: datetime
    window_key: str
    window_label: str
    cost_per_1k_lines: float | None
    repeat_rate: float | None
    repeat_time_rate: float | None
    read_only_cost_share: float | None
    read_write_ratio: float | None
    unrated_sessions: int
    total_tokens: int
    estimated_cost_usd: float
    branches_idle_cost_usd: float
    behavior_supported: bool
    efficiency_supported: bool
    leaks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Snapshot":
        gen = data.get("generated_at")
        generated_at = datetime.fromisoformat(gen) if isinstance(gen, str) else datetime.now(timezone.utc)
        return cls(
            generated_at=generated_at,
            window_key=data.get("window_key") or "",
            window_label=data.get("window_label") or "",
            cost_per_1k_lines=data.get("cost_per_1k_lines"),
            repeat_rate=data.get("repeat_rate"),
            repeat_time_rate=data.get("repeat_time_rate"),
            read_only_cost_share=data.get("read_only_cost_share"),
            read_write_ratio=data.get("read_write_ratio"),
            unrated_sessions=int(data.get("unrated_sessions") or 0),
            total_tokens=int(data.get("total_tokens") or 0),
            estimated_cost_usd=float(data.get("estimated_cost_usd") or 0.0),
            branches_idle_cost_usd=float(data.get("branches_idle_cost_usd") or 0.0),
            behavior_supported=bool(data.get("behavior_supported", False)),
            efficiency_supported=bool(data.get("efficiency_supported", False)),
            leaks=list(data.get("leaks") or []),
        )


class StateStore:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.cache_dir / STATE_FILENAME

    def load(self) -> Snapshot | None:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            return Snapshot.from_dict(data)
        except Exception:
            return None

    def save(self, snapshot: Snapshot) -> None:
        try:
            self.state_path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
        except OSError:
            pass


def pct_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return ((a - b) / b) * 100.0 if b != 0 else None


def abs_diff(a: float | int | None, b: float | int | None) -> float:
    return (float(a or 0) - float(b or 0))
