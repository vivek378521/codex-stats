from __future__ import annotations

import gzip
import json
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any
from urllib import error, request

from . import __version__
from .config import Paths, PricingConfig, load_pricing_config
from .ingest import iter_session_details
from .metrics import details_for_last_days, parse_since_days, summarize_daily
from .models import DailyPoint, SessionDetails

OTLP_AGGREGATION_TEMPORALITY_DELTA = 1
OTLP_AGGREGATION_TEMPORALITY_CUMULATIVE = 2


def build_otlp_metrics_payload(
    paths: Paths,
    *,
    since: str | None = None,
    daily_days: int = 30,
    service_name: str = "codex-stats",
    resource_attributes: dict[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now().astimezone()
    details = _select_details(paths, since=since, now=current_time)
    pricing = load_pricing_config(paths)
    monotonic = since is None
    temporality = OTLP_AGGREGATION_TEMPORALITY_CUMULATIVE if monotonic else OTLP_AGGREGATION_TEMPORALITY_DELTA
    collection_time_ns = _datetime_to_unix_nano(current_time.astimezone(UTC))
    start_time_ns = _session_start_time_ns(details, current_time)

    metrics: list[dict[str, Any]] = []
    metrics.extend(_build_aggregate_sum_metrics(details, pricing, start_time_ns, collection_time_ns, monotonic, temporality))
    metrics.extend(_build_daily_gauge_metrics(paths, daily_days=daily_days, now=current_time))

    resource_kvs = {
        "service.name": service_name,
        "service.version": __version__,
        "codex.stats.source": "local",
    }
    if since:
        resource_kvs["codex.stats.window"] = since
    if resource_attributes:
        resource_kvs.update(resource_attributes)

    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": [_string_attribute(key, value) for key, value in sorted(resource_kvs.items())]},
                "scopeMetrics": [
                    {
                        "scope": {
                            "name": "codex-stats",
                            "version": __version__,
                        },
                        "metrics": metrics,
                    }
                ],
            }
        ]
    }


def write_otlp_metrics_json(
    paths: Paths,
    output_path: Path,
    *,
    since: str | None = None,
    daily_days: int = 30,
    service_name: str = "codex-stats",
    resource_attributes: dict[str, str] | None = None,
    now: datetime | None = None,
) -> Path:
    payload = build_otlp_metrics_payload(
        paths,
        since=since,
        daily_days=daily_days,
        service_name=service_name,
        resource_attributes=resource_attributes,
        now=now,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def post_otlp_metrics_json(
    paths: Paths,
    endpoint: str,
    *,
    since: str | None = None,
    daily_days: int = 30,
    service_name: str = "codex-stats",
    resource_attributes: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    gzip_payload: bool = False,
    timeout_seconds: float = 10.0,
    now: datetime | None = None,
) -> tuple[int, str]:
    payload = build_otlp_metrics_payload(
        paths,
        since=since,
        daily_days=daily_days,
        service_name=service_name,
        resource_attributes=resource_attributes,
        now=now,
    )
    encoded = json.dumps(payload).encode("utf-8")
    request_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if headers:
        request_headers.update(headers)
    if gzip_payload:
        encoded = gzip.compress(encoded)
        request_headers["Content-Encoding"] = "gzip"
        request_headers["Accept-Encoding"] = "gzip"

    otlp_request = request.Request(endpoint, data=encoded, headers=request_headers, method="POST")
    try:
        with request.urlopen(otlp_request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OTLP export failed with HTTP {exc.code}: {body or exc.reason}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OTLP export failed: {exc.reason}") from exc


def parse_key_value_pairs(values: list[str] | None) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for value in values or []:
        key, separator, raw_value = value.partition("=")
        if not separator or not key:
            raise ValueError(f"Expected KEY=VALUE, got: {value}")
        pairs[key] = raw_value
    return pairs


def _select_details(paths: Paths, *, since: str | None, now: datetime) -> list[SessionDetails]:
    if since:
        return details_for_last_days(paths, parse_since_days(since), now=now)
    return iter_session_details(paths)


def _build_aggregate_sum_metrics(
    details: list[SessionDetails],
    pricing: PricingConfig,
    start_time_ns: str,
    collection_time_ns: str,
    monotonic: bool,
    temporality: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[tuple[str, str], ...], dict[str, float]] = defaultdict(
        lambda: {
            "sessions": 0.0,
            "requests": 0.0,
            "tokens": 0.0,
            "input_tokens": 0.0,
            "output_tokens": 0.0,
            "cached_input_tokens": 0.0,
            "reasoning_output_tokens": 0.0,
            "estimated_cost_usd": 0.0,
        }
    )

    for detail in details:
        attribute_items = tuple(
            sorted(
                {
                    "project": detail.session.project_name,
                    "model": detail.session.model or "unknown",
                    "provider": detail.session.model_provider,
                }.items()
            )
        )
        bucket = grouped[attribute_items]
        bucket["sessions"] += 1
        bucket["requests"] += detail.request_count
        bucket["tokens"] += detail.effective_total_tokens()
        bucket["input_tokens"] += detail.input_tokens or 0
        bucket["output_tokens"] += detail.output_tokens or 0
        bucket["cached_input_tokens"] += detail.cached_input_tokens or 0
        bucket["reasoning_output_tokens"] += detail.reasoning_output_tokens or 0
        bucket["estimated_cost_usd"] += _estimate_detail_cost(detail, pricing)

    total_bucket = {
        "sessions": float(len(details)),
        "requests": float(sum(detail.request_count for detail in details)),
        "tokens": float(sum(detail.effective_total_tokens() for detail in details)),
        "input_tokens": float(sum(detail.input_tokens or 0 for detail in details)),
        "output_tokens": float(sum(detail.output_tokens or 0 for detail in details)),
        "cached_input_tokens": float(sum(detail.cached_input_tokens or 0 for detail in details)),
        "reasoning_output_tokens": float(sum(detail.reasoning_output_tokens or 0 for detail in details)),
        "estimated_cost_usd": float(sum(_estimate_detail_cost(detail, pricing) for detail in details)),
    }
    grouped[tuple()] = total_bucket

    metric_specs = [
        ("codex_stats_sessions", "Count of Codex sessions in the exported snapshot.", "1", "sessions", True),
        ("codex_stats_requests", "Count of user requests observed in rollout JSONL.", "1", "requests", True),
        ("codex_stats_tokens", "Total tokens attributed to Codex sessions.", "1", "tokens", True),
        ("codex_stats_input_tokens", "Total input tokens attributed to Codex sessions.", "1", "input_tokens", True),
        ("codex_stats_output_tokens", "Total output tokens attributed to Codex sessions.", "1", "output_tokens", True),
        (
            "codex_stats_cached_input_tokens",
            "Total cached input tokens attributed to Codex sessions.",
            "1",
            "cached_input_tokens",
            True,
        ),
        (
            "codex_stats_reasoning_output_tokens",
            "Total reasoning output tokens attributed to Codex sessions.",
            "1",
            "reasoning_output_tokens",
            True,
        ),
        (
            "codex_stats_estimated_cost_usd",
            "Estimated Codex session cost in USD derived from local pricing config.",
            "USD",
            "estimated_cost_usd",
            False,
        ),
    ]

    metrics: list[dict[str, Any]] = []
    for name, description, unit, field_name, integer_value in metric_specs:
        data_points = []
        for attribute_items, bucket in sorted(grouped.items()):
            value = bucket[field_name]
            point = {
                "attributes": [_string_attribute(key, val) for key, val in attribute_items],
                "startTimeUnixNano": start_time_ns,
                "timeUnixNano": collection_time_ns,
            }
            if integer_value:
                point["asInt"] = str(int(value))
            else:
                point["asDouble"] = round(value, 6)
            data_points.append(point)

        metrics.append(
            {
                "name": name,
                "description": description,
                "unit": unit,
                "sum": {
                    "aggregationTemporality": temporality,
                    "isMonotonic": monotonic,
                    "dataPoints": data_points,
                },
            }
        )
    return metrics


def _build_daily_gauge_metrics(paths: Paths, *, daily_days: int, now: datetime) -> list[dict[str, Any]]:
    points = summarize_daily(paths, days=daily_days, now=now)
    return [
        _daily_gauge_metric(
            "codex_stats_daily_tokens",
            "Daily total tokens derived from local Codex sessions.",
            "1",
            points,
            now.tzinfo,
            lambda point: ("asInt", str(point.total_tokens)),
        ),
        _daily_gauge_metric(
            "codex_stats_daily_requests",
            "Daily total user requests derived from rollout JSONL.",
            "1",
            points,
            now.tzinfo,
            lambda point: ("asInt", str(point.requests)),
        ),
        _daily_gauge_metric(
            "codex_stats_daily_estimated_cost_usd",
            "Daily estimated Codex session cost in USD.",
            "USD",
            points,
            now.tzinfo,
            lambda point: ("asDouble", round(point.estimated_cost_usd, 6)),
        ),
    ]


def _daily_gauge_metric(
    name: str,
    description: str,
    unit: str,
    points: list[DailyPoint],
    timezone: tzinfo | None,
    value_builder,
) -> dict[str, Any]:
    data_points = []
    for point in points:
        timestamp = datetime.fromisoformat(point.day).replace(tzinfo=timezone or UTC)
        sample_time = datetime.combine(timestamp.date(), time(hour=23, minute=59, second=59), tzinfo=timestamp.tzinfo)
        key, value = value_builder(point)
        data_points.append(
            {
                "timeUnixNano": _datetime_to_unix_nano(sample_time.astimezone(UTC)),
                key: value,
            }
        )
    return {
        "name": name,
        "description": description,
        "unit": unit,
        "gauge": {"dataPoints": data_points},
    }


def _session_start_time_ns(details: list[SessionDetails], now: datetime) -> str:
    timestamps: list[datetime] = []
    for detail in details:
        if detail.started_at:
            timestamps.append(detail.started_at.astimezone(UTC))
        else:
            timestamps.append(detail.session.created_at.astimezone(UTC))
    start_time = min(timestamps, default=now.astimezone(UTC) - timedelta(seconds=1))
    return _datetime_to_unix_nano(start_time)


def _datetime_to_unix_nano(value: datetime) -> str:
    return str(int(value.timestamp() * 1_000_000_000))


def _string_attribute(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def _estimate_detail_cost(detail: SessionDetails, pricing: PricingConfig) -> float:
    total_tokens = detail.effective_total_tokens()
    return round((total_tokens / 1000.0) * pricing.rate_for_model(detail.session.model), 6)
