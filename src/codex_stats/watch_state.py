from __future__ import annotations

import json
from dataclasses import dataclass

from .config import Paths


@dataclass(frozen=True)
class WatchState:
    seen_session_ids: set[str]
    seen_alert_keys: set[tuple[str, str]]


def load_watch_state(paths: Paths, scope_key: str) -> WatchState:
    if not paths.watch_state_file.exists():
        return WatchState(seen_session_ids=set(), seen_alert_keys=set())
    try:
        payload = json.loads(paths.watch_state_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return WatchState(seen_session_ids=set(), seen_alert_keys=set())

    scopes = payload.get("scopes", {})
    scope = scopes.get(scope_key, {})
    seen_session_ids = {str(value) for value in scope.get("seen_session_ids", [])}
    seen_alert_keys = {
        (str(item[0]), str(item[1]))
        for item in scope.get("seen_alert_keys", [])
        if isinstance(item, list | tuple) and len(item) == 2
    }
    return WatchState(seen_session_ids=seen_session_ids, seen_alert_keys=seen_alert_keys)


def save_watch_state(
    paths: Paths,
    scope_key: str,
    *,
    seen_session_ids: set[str],
    seen_alert_keys: set[tuple[str, str]],
) -> None:
    payload = {"scopes": {}}
    if paths.watch_state_file.exists():
        try:
            payload = json.loads(paths.watch_state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {"scopes": {}}
    scopes = payload.setdefault("scopes", {})
    scopes[scope_key] = {
        "seen_session_ids": sorted(seen_session_ids),
        "seen_alert_keys": [list(item) for item in sorted(seen_alert_keys)],
    }
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.watch_state_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def build_watch_scope_key(
    *,
    days: int,
    project_name: str | None,
    cost_threshold_usd: float | None,
    token_threshold: int | None,
    request_threshold: int | None,
    delta_pct_threshold: float | None,
) -> str:
    return "|".join(
        [
            f"days={days}",
            f"project={project_name or ''}",
            f"cost={'' if cost_threshold_usd is None else cost_threshold_usd}",
            f"tokens={'' if token_threshold is None else token_threshold}",
            f"requests={'' if request_threshold is None else request_threshold}",
            f"delta={'' if delta_pct_threshold is None else delta_pct_threshold}",
        ]
    )
