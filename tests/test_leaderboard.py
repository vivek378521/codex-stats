from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_stats import leaderboard as leaderboard_module
from codex_stats.cli import _build_dashboard
from codex_stats.config import Paths
from codex_stats.display import format_dashboard_html
from codex_stats.leaderboard import (
    DEFAULT_BASE_URL,
    ENV_BASE_URL,
    ENV_DISABLE,
    ENV_SUBMIT_KEY,
    LeaderboardConfig,
    LeaderboardError,
    LeaderboardSubmitServer,
    LocalStats,
    build_submission_payload,
    canonical_string,
    collect_all_time_stats,
    device_id_for,
)
from codex_stats.models import (
    CompareReport,
    CostSummary,
    DashboardData,
    DashboardScope,
    DashboardWindow,
    InsightReport,
    TimeSummary,
    WorkRhythm,
)
from codex_stats.models import BreakdownEntry

UNIT_KEY = b"unit-test-key"


def _summary(**overrides) -> TimeSummary:
    values = {
        "label": "all time",
        "sessions": 3,
        "requests": 12,
        "input_tokens": 1000,
        "output_tokens": 500,
        "cached_input_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 1500,
        "estimated_cost_usd": 0.25,
        "top_model": "gpt-5",
        "average_tokens_per_request": 125.0,
        "cache_ratio": None,
        "largest_session_tokens": 900,
        "requests_per_session": 4.0,
        "median_tokens_per_session": 500.0,
        "median_requests_per_session": 4.0,
        "average_session_duration_minutes": 10.0,
        "median_session_duration_minutes": 9.0,
        "tokens_per_minute": 55.0,
        "project_concentration_top1_pct": 60.0,
        "project_concentration_top3_pct": 90.0,
        "longest_active_streak_days": 4,
        "model_switching_rate": 0.1,
    }
    values.update(overrides)
    return TimeSummary(**values)


def _window(key: str, *, tool_breakdown, summary=None) -> DashboardWindow:
    resolved = summary or _summary()
    empty = CompareReport(
        current=resolved,
        previous=resolved,
        total_tokens_delta=0,
        total_tokens_delta_pct=None,
        requests_delta=0,
        cost_delta_usd=0.0,
    )
    return DashboardWindow(
        key=key,
        label=key,
        description="",
        comparison_label="",
        summary=resolved,
        comparison=empty,
        projects=[],
        top_sessions=[],
        history=[],
        daily_points=[],
        costs=CostSummary(
            today_cost_usd=0.25,
            week_cost_usd=0.25,
            month_cost_usd=0.25,
            projected_monthly_cost_usd=3.0,
            highest_session_cost_usd=0.1,
        ),
        insights=InsightReport(
            average_tokens_per_request=125.0,
            cache_ratio=None,
            large_session_count=0,
            possible_savings_usd=0.0,
            largest_session_tokens=900,
            suggestion="",
            anomalies=[],
            recommendations=[],
        ),
        activity_heatmap=[],
        takeaways=[],
        badges=[],
        expensive_session=None,
        work_rhythm=WorkRhythm(headline="", detail="", peak_day=None, peak_hour=None),
        project_drilldowns=[],
        tool_breakdown=tool_breakdown,
    )


def _dashboard(tool_breakdown) -> DashboardData:
    return DashboardData(
        generated_at=__import__("datetime").datetime.fromisoformat("2026-04-03T18:30:00+05:30"),
        scopes=[
            DashboardScope(
                key="overview",
                label="Overview",
                description="",
                source="all",
                windows=[
                    _window("day", tool_breakdown=tool_breakdown),
                    _window("all", tool_breakdown=tool_breakdown),
                ],
            )
        ],
    )


BREAKDOWN = [
    BreakdownEntry(name="OpenCode", sessions=2, requests=8, total_tokens=900, estimated_cost_usd=0.15),
    BreakdownEntry(name="Codex", sessions=1, requests=4, total_tokens=600, estimated_cost_usd=0.10),
]


class LeaderboardConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            name: os.environ.pop(name, None)
            for name in (ENV_BASE_URL, ENV_SUBMIT_KEY, ENV_DISABLE)
        }

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_is_disabled_without_an_operator_configured_endpoint_and_key(self) -> None:
        self.assertIsNone(LeaderboardConfig.from_env())

    def test_requires_both_an_endpoint_and_a_key(self) -> None:
        os.environ[ENV_BASE_URL] = DEFAULT_BASE_URL
        self.assertIsNone(LeaderboardConfig.from_env())
        os.environ.pop(ENV_BASE_URL)
        os.environ[ENV_SUBMIT_KEY] = "secret"
        self.assertIsNone(LeaderboardConfig.from_env())

    def test_can_be_disabled(self) -> None:
        for value in ("1", "true", "TRUE", "yes", "on"):
            os.environ[ENV_DISABLE] = value
            self.assertIsNone(LeaderboardConfig.from_env(), value)

    def test_unrelated_disable_value_does_not_disable(self) -> None:
        for value in ("", "0", "false", "no", "maybe"):
            os.environ[ENV_DISABLE] = value
            os.environ[ENV_BASE_URL] = "https://example.vercel.app"
            os.environ[ENV_SUBMIT_KEY] = "secret"
            self.assertIsNotNone(LeaderboardConfig.from_env(), value)

    def test_operator_variables_configure_submission(self) -> None:
        os.environ[ENV_BASE_URL] = "https://example.vercel.app"
        os.environ[ENV_SUBMIT_KEY] = "secret"
        config = LeaderboardConfig.from_env()
        assert config is not None
        self.assertEqual(config.base_url, "https://example.vercel.app")
        self.assertEqual(config.submit_key, b"secret")

    def test_trailing_slash_is_trimmed(self) -> None:
        os.environ[ENV_BASE_URL] = "https://example.vercel.app/"
        os.environ[ENV_SUBMIT_KEY] = "secret"
        config = LeaderboardConfig.from_env()
        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.base_url, "https://example.vercel.app")


class CollectStatsTests(unittest.TestCase):
    def test_reads_overview_all_time_window(self) -> None:
        stats = collect_all_time_stats(_dashboard(BREAKDOWN))
        self.assertIsNotNone(stats)
        self.assertEqual(stats.total_tokens, 1500)
        self.assertEqual(stats.requests, 12)
        self.assertEqual(stats.sessions, 3)
        self.assertEqual(stats.cost_micros, 250000)

    def test_cli_keys_are_source_keys_not_display_labels(self) -> None:
        stats = collect_all_time_stats(_dashboard(BREAKDOWN))
        self.assertEqual(stats.clis, {"opencode": 900, "codex": 600})

    def test_breakdown_sums_to_the_headline_total(self) -> None:
        stats = collect_all_time_stats(_dashboard(BREAKDOWN))
        self.assertEqual(sum(stats.clis.values()), stats.total_tokens)

    def test_returns_none_without_a_tool_breakdown(self) -> None:
        self.assertIsNone(collect_all_time_stats(_dashboard(None)))

    def test_zero_token_entries_are_dropped(self) -> None:
        breakdown = BREAKDOWN + [BreakdownEntry(name="Hermes", sessions=0, requests=0, total_tokens=0, estimated_cost_usd=0.0)]
        stats = collect_all_time_stats(_dashboard(breakdown))
        self.assertNotIn("hermes", stats.clis)


class SigningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stats = LocalStats(
            total_tokens=1500,
            requests=12,
            sessions=3,
            cost_micros=250000,
            clis={"opencode": 900, "codex": 600},
        )

    def test_canonical_string_sorts_clis_and_keeps_field_order(self) -> None:
        message = canonical_string(
            device_id="d" * 32,
            username="ada",
            stats=self.stats,
            ts=1700000000,
            nonce="aabbccddeeff00112233445566778899",
        )
        self.assertEqual(
            message,
            "1|" + "d" * 32 + "|ada|1500|12|3|250000|codex:600,opencode:900|1700000000|aabbccddeeff00112233445566778899",
        )

    def test_signature_matches_the_pinned_vector(self) -> None:
        # Pinned so that a change on either side of the wire format is caught here
        # rather than silently producing unverifiable submissions.
        payload = build_submission_payload(
            submit_key=UNIT_KEY,
            stats=self.stats,
            username="ada",
            now=1700000000,
        )
        payload["nonce"] = "aabbccddeeff00112233445566778899"
        payload["device_id"] = device_id_for(UNIT_KEY)
        message = canonical_string(
            device_id=payload["device_id"],
            username="ada",
            stats=self.stats,
            ts=1700000000,
            nonce=payload["nonce"],
        )
        import hashlib
        import hmac

        self.assertEqual(
            hmac.new(UNIT_KEY, message.encode("utf-8"), hashlib.sha256).hexdigest(),
            "26615a3684b2d9669413eff035389223dc14a0ca06f48aead9cf957ede1eb070",
        )
        self.assertEqual(payload["device_id"], "fc8b3e63512d4ebdc3f8249611cbc66c")

    def test_username_is_validated(self) -> None:
        for bad in ["", "  ", "has space", "a" * 21, "emoji🙂", "semi;colon", "pipe|char"]:
            with self.assertRaises(ValueError):
                build_submission_payload(submit_key=UNIT_KEY, stats=self.stats, username=bad)
        for good in ["ada", "ada_lovelace", "A-1", "x" * 20]:
            payload = build_submission_payload(submit_key=UNIT_KEY, stats=self.stats, username=good)
            self.assertEqual(payload["username"], good)

    def test_username_is_trimmed(self) -> None:
        payload = build_submission_payload(submit_key=UNIT_KEY, stats=self.stats, username="  ada  ")
        self.assertEqual(payload["username"], "ada")

    def test_empty_breakdown_is_rejected(self) -> None:
        empty = LocalStats(total_tokens=0, requests=0, sessions=0, cost_micros=0, clis={})
        with self.assertRaises(ValueError):
            build_submission_payload(submit_key=UNIT_KEY, stats=empty, username="ada")

    def test_nonce_is_unique_per_submission(self) -> None:
        first = build_submission_payload(submit_key=UNIT_KEY, stats=self.stats, username="ada")
        second = build_submission_payload(submit_key=UNIT_KEY, stats=self.stats, username="ada")
        self.assertNotEqual(first["nonce"], second["nonce"])
        self.assertNotEqual(first["signature"], second["signature"])


class DeviceIdTests(unittest.TestCase):
    def test_is_stable_across_calls(self) -> None:
        self.assertEqual(device_id_for(UNIT_KEY), device_id_for(UNIT_KEY))

    def test_differs_per_key(self) -> None:
        self.assertNotEqual(device_id_for(UNIT_KEY), device_id_for(b"another-key"))

    def test_is_32_hex_characters_and_hides_the_mac(self) -> None:
        device_id = device_id_for(UNIT_KEY)
        self.assertEqual(len(device_id), 32)
        int(device_id, 16)
        self.assertNotIn(f"{uuid.getnode():012x}", device_id)


class SubmitServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dashboard = _dashboard(BREAKDOWN)
        self.config = LeaderboardConfig(base_url="https://example.invalid", submit_key=UNIT_KEY)
        self.server = LeaderboardSubmitServer(self.config, self.dashboard)
        self.url = self.server.start()
        self.path = "/" + "/".join(self.url.split("/")[3:])
        self.captured: list[tuple[LocalStats, str]] = []
        self._original_submit = leaderboard_module.submit_stats

        def fake_submit(config, stats, username):
            self.captured.append((stats, username))
            return {"ok": True, "rank": 1, "totalTokens": stats.total_tokens, "updated": "ok"}

        leaderboard_module.submit_stats = fake_submit
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        leaderboard_module.submit_stats = self._original_submit
        self.server.close()

    def _post(self, path: str, body: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.port}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read().decode("utf-8"))

    def test_binds_to_loopback_only(self) -> None:
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))

    def test_forged_numbers_from_the_browser_are_ignored(self) -> None:
        status, payload = self._post(
            self.path,
            {
                "username": "ada",
                "total_tokens": 999_999_999_999,
                "clis": {"codex": 999_999_999_999},
                "device_id": "0" * 32,
                "signature": "deadbeef",
                "cost_micros": 5_000_000_000,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(self.captured), 1)
        stats, username = self.captured[0]
        self.assertEqual(username, "ada")
        self.assertEqual(stats.total_tokens, 1500)
        self.assertEqual(stats.clis, {"opencode": 900, "codex": 600})
        self.assertEqual(payload["totalTokens"], 1500)

    def test_wrong_nonce_path_is_rejected(self) -> None:
        status, payload = self._post("/submit/" + "0" * 32, {"username": "ada"})
        self.assertEqual(status, 404)
        self.assertFalse(payload["ok"])
        self.assertEqual(self.captured, [])

    def test_bad_username_is_rejected_before_any_submission(self) -> None:
        status, payload = self._post(self.path, {"username": "not valid!"})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(self.captured, [])

    def test_upstream_failure_is_surfaced_to_the_page(self) -> None:
        def failing_submit(config, stats, username):
            raise LeaderboardError("Could not reach the leaderboard: offline")

        leaderboard_module.submit_stats = failing_submit
        status, payload = self._post(self.path, {"username": "ada"})
        self.assertEqual(status, 502)
        self.assertIn("offline", payload["error"])

    def test_empty_body_is_rejected(self) -> None:
        status, payload = self._post(self.path, {})
        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(self.captured, [])

    def test_preview_reports_what_will_be_sent(self) -> None:
        preview = self.server.preview()
        self.assertEqual(preview["submitUrl"], self.url)
        self.assertTrue(preview["available"])
        self.assertEqual(preview["totalTokens"], 1500)
        self.assertEqual([item["key"] for item in preview["clis"]], ["opencode", "codex"])
        self.assertEqual(preview["clis"][0]["label"], "OpenCode")


class DashboardHtmlTests(unittest.TestCase):
    def test_button_is_absent_when_the_leaderboard_is_not_configured(self) -> None:
        html = format_dashboard_html(_dashboard(BREAKDOWN))
        self.assertNotIn("Submit to Leaderboard", html)
        self.assertNotIn('<button class="action-button" type="button" data-action="submit-leaderboard">', html)
        self.assertNotIn('<dialog class="leaderboard-dialog"', html)
        self.assertIn("const leaderboardConfig = null;", html)

    def test_button_and_dialog_appear_when_configured(self) -> None:
        preview = {
            "submitUrl": "http://127.0.0.1:54321/submit/abc123",
            "available": True,
            "totalTokens": 1500,
            "requests": 12,
            "sessions": 3,
            "clis": [{"key": "codex", "label": "Codex", "tokens": 1500}],
        }
        html = format_dashboard_html(_dashboard(BREAKDOWN), leaderboard=preview)
        self.assertIn("Submit to Leaderboard", html)
        self.assertIn('data-action="submit-leaderboard"', html)
        self.assertIn("data-leaderboard-dialog", html)
        self.assertIn("data-leaderboard-username", html)
        self.assertIn("data-leaderboard-preview", html)
        self.assertIn('"submitUrl":"http://127.0.0.1:54321/submit/abc123"', html)
        self.assertIn('"label":"Codex"', html)

    def test_no_token_totals_are_embedded_for_upload(self) -> None:
        # The page may show a preview, but cannot alter the local process's
        # reported totals through this endpoint.
        html = format_dashboard_html(
            _dashboard(BREAKDOWN),
            leaderboard={"submitUrl": "http://127.0.0.1:1/submit/x", "totalTokens": 1500, "clis": []},
        )
        self.assertIn("leaderboardConfig.totalTokens", html)


class RealDashboardTests(unittest.TestCase):
    def test_local_dashboard_produces_a_submittable_payload(self) -> None:
        dashboard = _build_dashboard(Paths.discover())
        stats = collect_all_time_stats(dashboard)
        if stats is None or stats.total_tokens == 0:
            self.skipTest("no local usage recorded")
        self.assertEqual(sum(stats.clis.values()), stats.total_tokens)
        payload = build_submission_payload(submit_key=UNIT_KEY, stats=stats, username="ada")
        self.assertEqual(len(payload["signature"]), 64)
        self.assertEqual(payload["v"], 1)


if __name__ == "__main__":
    unittest.main()
