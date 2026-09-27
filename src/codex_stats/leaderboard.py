"""Leaderboard submission.

The browser is never trusted with a number. The dashboard can only send a
username; the token totals are read here, out of the already-computed
``DashboardData``, and signed with a key that only ever exists in this process
and in the server's environment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .models import DashboardData, DashboardWindow
from .sources import SOURCE_LABELS

PROTOCOL_VERSION = 1
ENV_BASE_URL = "CODEX_STATS_LEADERBOARD_URL"
ENV_SUBMIT_KEY = "CODEX_STATS_LEADERBOARD_KEY"
SUBMIT_ENDPOINT = "/api/submit"
REQUEST_TIMEOUT_SECONDS = 15.0
MAX_BODY_BYTES = 4096
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,20}$")

# Baked in so a fresh install can submit with no setup. The env vars still win,
# which is what lets the key be rotated without cutting a release, and lets
# tests point at a local server.
#
# This is a deliberate integrity trade-off, not a secret worth protecting. Once
# this ships, the key is public, so anyone can sign a submission for their own
# device id. What stays protected: stats still come from the local database
# rather than the browser, device ids are not disclosed by the read API, and no
# one can overwrite another person's row without knowing their id. What is lost
# is the ability to stop someone claiming a larger number for themselves, or
# flooding the board with invented rows. Guarding against that has to happen
# server-side (rate limits, row caps), not here.
DEFAULT_BASE_URL = "https://codex-stats-leaderboard.vercel.app"
DEFAULT_SUBMIT_KEY = "554f68344e64f04e870de3640b7bf5a35d33903f2d084a0b679fca54a7959cf3"

# Submitting publishes a username and token totals to a third-party server, so
# there has to be a way to refuse that even though the feature is now on by
# default. This is the only way to get the button back to hidden.
ENV_DISABLE = "CODEX_STATS_DISABLE_LEADERBOARD"
_TRUTHY = {"1", "true", "yes", "on"}

# ``tool_breakdown`` entries carry display labels, so map them back to source keys.
_LABEL_TO_SOURCE = {label: key for key, label in SOURCE_LABELS.items()}


class LeaderboardError(RuntimeError):
    """A submission could not be completed."""


@dataclass(frozen=True)
class LeaderboardConfig:
    base_url: str
    submit_key: bytes

    @classmethod
    def from_env(cls) -> LeaderboardConfig | None:
        if os.environ.get(ENV_DISABLE, "").strip().lower() in _TRUTHY:
            return None
        base_url = os.environ.get(ENV_BASE_URL, "").strip() or DEFAULT_BASE_URL
        submit_key = os.environ.get(ENV_SUBMIT_KEY, "").strip() or DEFAULT_SUBMIT_KEY
        if not base_url or not submit_key:
            return None
        return cls(base_url=base_url.rstrip("/"), submit_key=submit_key.encode("utf-8"))


@dataclass(frozen=True)
class LocalStats:
    total_tokens: int
    requests: int
    sessions: int
    cost_micros: int
    clis: dict[str, int]


def _all_time_overview_window(dashboard: DashboardData) -> DashboardWindow | None:
    for scope in dashboard.scopes:
        if scope.key != "overview":
            continue
        for window in scope.windows:
            if window.key == "all":
                return window
    return None


def collect_all_time_stats(dashboard: DashboardData) -> LocalStats | None:
    """Read the all-time, all-tools totals that the dashboard already computed."""
    window = _all_time_overview_window(dashboard)
    if window is None or not window.tool_breakdown:
        return None
    clis: dict[str, int] = {}
    for entry in window.tool_breakdown:
        source_key = _LABEL_TO_SOURCE.get(entry.name, entry.name.strip().lower())
        clis[source_key] = clis.get(source_key, 0) + int(entry.total_tokens)
    summary = window.summary
    return LocalStats(
        total_tokens=int(summary.total_tokens),
        requests=int(summary.requests),
        sessions=int(summary.sessions),
        cost_micros=int(round(summary.estimated_cost_usd * 1_000_000)),
        clis={key: value for key, value in clis.items() if value > 0},
    )


def device_id_for(submit_key: bytes) -> str:
    """A stable, opaque per-machine id.

    The MAC address is read locally and never transmitted; only this HMAC of it
    leaves the machine, so the raw hardware address is not stored anywhere.
    """
    material = f"codex-stats-device:{uuid.getnode():012x}".encode("utf-8")
    return hmac.new(submit_key, material, hashlib.sha256).hexdigest()[:32]


def canonical_string(
    *,
    device_id: str,
    username: str,
    stats: LocalStats,
    ts: int,
    nonce: str,
) -> str:
    """The exact string that gets signed.

    Must stay byte-identical to ``canonicalString`` in the leaderboard app's
    ``lib/signing.js``. A pipe-delimited string is used rather than JSON so the
    two runtimes cannot disagree about key order, floats, or unicode escaping.
    """
    clis = ",".join(f"{key}:{value}" for key, value in sorted(stats.clis.items()) if value > 0)
    return "|".join(
        (
            str(PROTOCOL_VERSION),
            device_id,
            username,
            str(stats.total_tokens),
            str(stats.requests),
            str(stats.sessions),
            str(stats.cost_micros),
            clis,
            str(ts),
            nonce,
        )
    )


def build_submission_payload(
    *,
    submit_key: bytes,
    stats: LocalStats,
    username: str,
    now: float | None = None,
) -> dict[str, Any]:
    handle = username.strip()
    if not USERNAME_PATTERN.match(handle):
        raise ValueError("Username must be 1-20 characters of A-Z, a-z, 0-9, _ or -.")
    if not stats.clis:
        raise ValueError("No CLI usage found to submit.")
    ts = int(now if now is not None else time.time())
    nonce = secrets.token_hex(16)
    device_id = device_id_for(submit_key)
    message = canonical_string(
        device_id=device_id,
        username=handle,
        stats=stats,
        ts=ts,
        nonce=nonce,
    )
    return {
        "v": PROTOCOL_VERSION,
        "device_id": device_id,
        "username": handle,
        "total_tokens": stats.total_tokens,
        "requests": stats.requests,
        "sessions": stats.sessions,
        "cost_micros": stats.cost_micros,
        "clis": stats.clis,
        "ts": ts,
        "nonce": nonce,
        "signature": hmac.new(submit_key, message.encode("utf-8"), hashlib.sha256).hexdigest(),
    }


def submit_stats(config: LeaderboardConfig, stats: LocalStats, username: str) -> dict[str, Any]:
    payload = build_submission_payload(submit_key=config.submit_key, stats=stats, username=username)
    request = urllib.request.Request(
        f"{config.base_url}{SUBMIT_ENDPOINT}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = _error_detail(error)
        raise LeaderboardError(detail or f"Leaderboard rejected the submission (HTTP {error.code}).") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise LeaderboardError(f"Could not reach the leaderboard: {error.reason if hasattr(error, 'reason') else error}") from error
    except json.JSONDecodeError as error:
        raise LeaderboardError("Leaderboard returned an unreadable response.") from error
    if not isinstance(body, dict):
        raise LeaderboardError("Leaderboard returned an unexpected response.")
    if not body.get("ok"):
        raise LeaderboardError(str(body.get("error") or "Leaderboard rejected the submission."))
    return body


def _error_detail(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        return ""
    if isinstance(payload, dict):
        return str(payload.get("error") or "")
    return ""


class LeaderboardSubmitServer:
    """A loopback-only endpoint that turns a username into a signed submission.

    The dashboard posts to this server. Only the username crosses that hop; the
    numbers are read from the dashboard object this server was built with, so
    editing the generated HTML cannot change what is reported. The per-run nonce
    in the path means another page in the same browser cannot drive this server.
    """

    def __init__(self, config: LeaderboardConfig, dashboard: DashboardData) -> None:
        self._config = config
        self._dashboard = dashboard
        self._nonce = secrets.token_hex(16)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.submit_url: str = ""
        self.port: int = 0

    def start(self) -> str:
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _build_handler(self))
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="codex-stats-leaderboard",
            daemon=True,
        )
        self._thread.start()
        host, port = self._httpd.server_address[:2]
        self.port = port
        self.submit_url = f"http://{host}:{port}/submit/{self._nonce}"
        return self.submit_url

    def preview(self) -> dict[str, Any]:
        stats = collect_all_time_stats(self._dashboard)
        return {
            "submitUrl": self.submit_url,
            "available": stats is not None,
            "totalTokens": stats.total_tokens if stats else 0,
            "requests": stats.requests if stats else 0,
            "sessions": stats.sessions if stats else 0,
            "clis": [
                {"key": key, "label": SOURCE_LABELS.get(key, key), "tokens": value}
                for key, value in sorted((stats.clis if stats else {}).items(), key=lambda item: -item[1])
            ],
        }

    def wait(self) -> None:
        if self._thread is not None:
            self._thread.join()

    def close(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def _build_handler(server: LeaderboardSubmitServer) -> type[BaseHTTPRequestHandler]:
    expected_path = f"/submit/{server._nonce}"

    class SubmitHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "codex-stats"

        def do_POST(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
            if self.path != expected_path:
                self._respond(404, {"ok": False, "error": "Not found."})
                return
            username = self._read_username()
            if username is None:
                return
            stats = collect_all_time_stats(server._dashboard)
            if stats is None:
                self._respond(
                    409,
                    {"ok": False, "error": "No all-time totals are available to submit yet."},
                )
                return
            try:
                result = submit_stats(server._config, stats, username)
            except LeaderboardError as error:
                self._respond(502, {"ok": False, "error": str(error)})
                return
            except ValueError as error:
                self._respond(400, {"ok": False, "error": str(error)})
                return
            self._respond(200, result)

        def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
            self._respond(405, {"ok": False, "error": "Use POST."})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_username(self) -> str | None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY_BYTES:
                self._respond(400, {"ok": False, "error": "Invalid request body."})
                return None
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._respond(400, {"ok": False, "error": "Invalid request body."})
                return None
            if not isinstance(body, dict):
                self._respond(400, {"ok": False, "error": "Invalid request body."})
                return None
            username = str(body.get("username") or "").strip()
            if not USERNAME_PATTERN.match(username):
                self._respond(
                    400,
                    {"ok": False, "error": "Username must be 1-20 characters of A-Z, a-z, 0-9, _ or -."},
                )
                return None
            return username

        def _respond(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            # The dashboard is served from a file:// URL, so its origin is opaque
            # and the browser treats this as a cross-origin request. The nonce in
            # the path, not this header, is what actually gates access.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return SubmitHandler
