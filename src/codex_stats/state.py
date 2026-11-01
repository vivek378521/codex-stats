from __future__ import annotations

import json
import os
import pickle
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILENAME = "last_snapshot.json"
INGEST_CACHE_FILENAME = "ingest_cache.pkl"
INGEST_CACHE_VERSION = 2


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


class IngestCache:
    """Per-source parse cache keyed by a cheap filesystem fingerprint.

    Parsing every historical transcript on every run is the slowest part of the
    dashboard. The cache stores the already-parsed ``SessionDetails`` and only
    reuses them while the source's file count, total size and newest mtime are
    unchanged. ``CODEX_STATS_MAX_SESSIONS`` is part of the fingerprint because a
    different cap legitimately produces a different session list.
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / INGEST_CACHE_FILENAME
        self._data = self._read()

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            with self.cache_path.open("rb") as handle:
                payload = pickle.load(handle)
        except (FileNotFoundError, EOFError, OSError, pickle.PickleError, AttributeError, ValueError):
            return {}
        if not isinstance(payload, dict) or payload.get("version") != INGEST_CACHE_VERSION:
            return {}
        sources = payload.get("sources")
        return sources if isinstance(sources, dict) else {}

    def get(self, source_key: str, fingerprint: str | None) -> list[Any] | None:
        if not fingerprint:
            return None
        item = self._data.get(source_key)
        if not isinstance(item, dict) or item.get("fingerprint") != fingerprint:
            return None
        details = item.get("details")
        return details if isinstance(details, list) else None

    def put(self, source_key: str, fingerprint: str | None, details: list[Any]) -> None:
        if not fingerprint:
            return
        self._data[source_key] = {"fingerprint": fingerprint, "details": details}

    def save(self) -> None:
        payload = {"version": INGEST_CACHE_VERSION, "sources": self._data}
        try:
            fd, temp_name = tempfile.mkstemp(
                prefix=".ingest-", suffix=".tmp", dir=self.cache_dir
            )
            try:
                with os.fdopen(fd, "wb") as handle:
                    pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
                os.replace(temp_name, self.cache_path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        except OSError:
            pass


def ingest_fingerprint(path_hint: str, max_sessions: str) -> str | None:
    """Cheap fingerprint for a directory or database, or None if unreadable."""
    path = Path(path_hint).expanduser()
    try:
        if path.is_file():
            stat = path.stat()
            marker = (1, stat.st_size, stat.st_mtime_ns)
        elif path.is_dir():
            count = 0
            total_size = 0
            newest = 0
            for root, _dirs, files in os.walk(path):
                for name in files:
                    try:
                        stat = os.stat(os.path.join(root, name))
                    except OSError:
                        continue
                    count += 1
                    total_size += stat.st_size
                    newest = max(newest, stat.st_mtime_ns)
            marker = (count, total_size, newest)
        else:
            return None
    except OSError:
        return None
    return "|".join(str(part) for part in (INGEST_CACHE_VERSION, sys.version_info[:2], max_sessions, *marker))


def pct_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return ((a - b) / b) * 100.0 if b != 0 else None


def abs_diff(a: float | int | None, b: float | int | None) -> float:
    return (float(a or 0) - float(b or 0))
