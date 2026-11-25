from __future__ import annotations

import base64
import json
import os
import re
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Paths
from .dsh_ingest import dsh_sessions_dir
from .sources import (
    SOURCE_CLAUDE,
    SOURCE_CODEX,
    SOURCE_DSH,
    SOURCE_HERMES,
    SOURCE_OPENCODE,
)

REVIEWED_ON = "2026-11-25"

ON = "on"
OFF = "off"
OPT_IN = "opt-in"
MIXED = "mixed"
UNCLEAR = "unclear"
UNKNOWN = "unknown"

DISCLAIMER = (
    "Curated from vendor documentation, vendor source code and independent source "
    "review at the links below, reviewed " + REVIEWED_ON + ". Defaults change between "
    "releases and surfaces; the local settings below are read from this machine only "
    "and are the authoritative answer for this install. codex-stats does not upload "
    "this report anywhere."
)

_SENSITIVE_KEY = re.compile(r"(?i)(id|hash|token|secret|key|email|path|address|rh)")
_YAML_LINE = re.compile(r"^(\s*)([\w.-]+):\s*(.*?)\s*$")


@dataclass(frozen=True)
class Evidence:
    title: str
    url: str
    kind: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TelemetryProfile:
    key: str
    label: str
    default: str
    summary: str
    opt_out_short: str
    destinations: tuple[str, ...]
    categories: tuple[str, ...]
    content: str
    opt_out: str
    caveat: str
    evidence: tuple[Evidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "default": self.default,
            "summary": self.summary,
            "opt_out_short": self.opt_out_short,
            "destinations": list(self.destinations),
            "categories": list(self.categories),
            "content": self.content,
            "opt_out": self.opt_out,
            "caveat": self.caveat,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class LocalSetting:
    name: str
    value: str
    location: str
    state: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LocalObservation:
    label: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarnessTelemetry:
    profile: TelemetryProfile
    installed: bool
    local_summary: str
    settings: tuple[LocalSetting, ...] = ()
    observations: tuple[LocalObservation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "installed": self.installed,
            "local_summary": self.local_summary,
            "settings": [item.to_dict() for item in self.settings],
            "observations": [item.to_dict() for item in self.observations],
        }


@dataclass(frozen=True)
class TelemetryReport:
    generated_at: datetime
    harnesses: list[HarnessTelemetry] = field(default_factory=list)

    @property
    def disclaimer(self) -> str:
        return DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "reviewed_on": REVIEWED_ON,
            "disclaimer": DISCLAIMER,
            "harnesses": [item.to_dict() for item in self.harnesses],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def to_markdown(self) -> str:
        lines = [
            "# Coding agent telemetry disclosure",
            "",
            f"Generated {self.generated_at.strftime('%Y-%m-%d %H:%M %Z') or 'just now'}. "
            f"Curated facts reviewed {REVIEWED_ON}.",
            "",
            f"> {DISCLAIMER}",
            "",
        ]
        for item in self.harnesses:
            profile = item.profile
            lines.extend(
                [
                    f"## {profile.label}",
                    "",
                    f"- Installed here: {'yes' if item.installed else 'no local state found'}",
                    f"- On this machine: {item.local_summary}",
                    f"- Default: {profile.default}",
                    f"- Destinations: {', '.join(profile.destinations)}",
                    f"- Data: {'; '.join(profile.categories)}",
                    f"- Prompts and code: {profile.content}",
                    f"- Opt out: {profile.opt_out}",
                    f"- Caveat: {profile.caveat}",
                    "",
                ]
            )
            if item.settings:
                lines.extend(["Local settings:", ""])
                for setting in item.settings:
                    lines.append(
                        f"- `{setting.name}` = `{setting.value}` ({setting.location}, {setting.state})"
                    )
                lines.append("")
            if item.observations:
                lines.extend(["Observed locally:", ""])
                for observation in item.observations:
                    lines.append(f"- {observation.label}: {observation.detail}")
                lines.append("")
            lines.extend(["Evidence:", ""])
            for evidence in profile.evidence:
                lines.append(f"- [{evidence.title}]({evidence.url}) — {evidence.kind}: {evidence.detail}")
            lines.append("")
        return "\n".join(lines)

    def to_terminal(self) -> str:
        lines = ["Coding agent telemetry disclosure", ""]
        for item in self.harnesses:
            lines.append(f"{item.profile.label}: {item.local_summary}")
            lines.append(f"  default: {item.profile.default} | opt out: {item.profile.opt_out}")
        lines.extend(["", "Nothing was uploaded by codex-stats.", DISCLAIMER])
        return "\n".join(lines)


CODEX_PROFILE = TelemetryProfile(
    key=SOURCE_CODEX,
    label="Codex",
    default=MIXED,
    summary="Anonymous usage and health metrics. Prompts stay local unless you enable OTEL logging.",
    opt_out_short="[analytics] enabled = false",
    destinations=(
        "ab.chatgpt.com/otlp/v1/metrics (Statsig-format metrics)",
        "chatgpt.com backend-api/codex/analytics-events",
        "sentry.io (only for user-initiated /feedback)",
        "a collector you configure yourself (off by default)",
    ),
    categories=(
        "anonymous usage and health counters",
        "feature and config use",
        "API request counts by status",
        "tool names with durations and outcomes (not the command text)",
        "model, auth mode and Codex version tags",
    ),
    content=(
        "No prompts or code in built-in analytics. Opt-in OpenTelemetry logs can "
        "include user prompts, agent responses and guardian assessments; raw API "
        "bodies are not part of the built-in analytics channel."
    ),
    opt_out=(
        "[analytics] enabled = false in ~/.codex/config.toml; [feedback] enabled = false "
        "stops /feedback uploads; otel.exporter = \"none\" (default) keeps logs local"
    ),
    caveat=(
        "On for the interactive CLI and codex exec; off by default for codex app-server "
        "unless launched with --analytics-default-enabled. A custom OTLP exporter keeps "
        "running even with [analytics] disabled."
    ),
    evidence=(
        Evidence(
            "Codex Client Analytics announcement",
            "https://github.com/openai/codex/discussions/8291",
            "vendor docs",
            "Anonymous analytics default on where permitted; no PII; opt-out flag promised.",
        ),
        Evidence(
            "Codex advanced configuration and metrics catalog",
            "https://developers.openai.com/codex/config-advanced/",
            "vendor docs",
            "Lists the metric categories and the [analytics] and otel controls.",
        ),
        Evidence(
            "OpenTelemetry README in openai/codex",
            "https://github.com/openai/codex/blob/main/codex-rs/otel/README.md",
            "vendor source",
            "Documents session events and the opt-in log_user_prompt / log_agent_responses flags.",
        ),
        Evidence(
            "AI coding tools telemetry audit",
            "https://getshadow.dev/research/ai-coding-tools-telemetry-audit/",
            "independent source review",
            "Maps exporters to ab.chatgpt.com, chatgpt.com and Sentry at a pinned commit.",
        ),
    ),
)

CLAUDE_PROFILE = TelemetryProfile(
    key=SOURCE_CLAUDE,
    label="Claude Code",
    default=MIXED,
    summary="Usage metrics and error reports. Prompts stay local unless you share feedback.",
    opt_out_short="CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
    destinations=(
        "api.anthropic.com",
        "third-party logging infrastructure over TLS",
        "third-party error tracking service over TLS",
        "a collector you configure yourself (off by default)",
    ),
    categories=(
        "latency, reliability and usage patterns",
        "error messages and stack traces from Claude Code internals",
        "session quality survey ratings",
        "WebFetch hostname preflight checks",
    ),
    content=(
        "Metrics never include code, prompts or file paths. Error reports are redacted "
        "for known secrets, paths and email addresses. Explicit /feedback, /bug and "
        "/share, or agreeing to transcript sharing, do upload conversation history "
        "including code."
    ),
    opt_out=(
        "DISABLE_TELEMETRY=1 and DISABLE_ERROR_REPORTING=1; DISABLE_FEEDBACK_COMMAND=1; "
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 disables all nonessential traffic "
        "including auto-updates; skipWebFetchPreflight in settings.json stops the hostname check"
    ),
    caveat=(
        "Metrics default on with the Claude API and off with Bedrock, Vertex, Foundry "
        "and Claude Platform on AWS. Error reporting needs a Pro/Max/Ultra sign-in on "
        "v2.1.198+ with a direct Claude API connection. Non-empty values of "
        "DISABLE_TELEMETRY count as set, even \"0\"."
    ),
    evidence=(
        Evidence(
            "Claude Code data usage",
            "https://code.claude.com/docs/en/data-usage",
            "vendor docs",
            "Defines metrics, error reports, feedback and survey defaults and opt-outs.",
        ),
        Evidence(
            "Claude Code monitoring and OpenTelemetry events",
            "https://code.claude.com/docs/en/monitoring-usage/",
            "vendor docs",
            "Lists event names and the flags that reveal prompts, responses and tool inputs.",
        ),
        Evidence(
            "AI coding tools telemetry audit",
            "https://getshadow.dev/research/ai-coding-tools-telemetry-audit/",
            "independent source review",
            "Confirms provider-dependent defaults and the scope of each env flag.",
        ),
    ),
)

OPENCODE_PROFILE = TelemetryProfile(
    key=SOURCE_OPENCODE,
    label="OpenCode",
    default=UNCLEAR,
    summary="No usage telemetry in the CLI. Fetches models and updates; shares only when you ask.",
    opt_out_short="OPENCODE_DISABLE_* flags; block Sentry for desktop",
    destinations=(
        "models.dev (model catalog)",
        "opencode.ai (auto-update check)",
        "app.opencode.ai (experimental web UI assets)",
        "opncd.ai (only when you share a session)",
        "Sentry ingest (reported in the desktop bundle by independent review)",
    ),
    categories=(
        "model catalog refreshes",
        "update checks",
        "explicit session shares",
        "desktop error and session-health events (independent finding)",
    ),
    content=(
        "Maintainers state the CLI collects no telemetry. Independent static review of "
        "desktop 1.16.2 found an ungated Sentry setup with breadcrumbs removed; an error "
        "stack trace could carry paths. No captured network traffic was published."
    ),
    opt_out=(
        "OPENCODE_DISABLE_MODELS_FETCH=1, OPENCODE_DISABLE_AUTOUPDATE=1, "
        "OPENCODE_DISABLE_SHARE=1 or \"share\": \"disabled\"; block the Sentry ingest "
        "host at the network layer if you need to stop desktop error reporting"
    ),
    caveat=(
        "The CLI and the Electron desktop app differ. There is no documented telemetry "
        "switch for the desktop Sentry path, and the Sentry claim comes from bundle "
        "inspection rather than a packet capture."
    ),
    evidence=(
        Evidence(
            "OpenCode maintainers on telemetry",
            "https://github.com/anomalyco/opencode/issues/459",
            "vendor statement",
            "No telemetry collected; background requests go to models.dev and update checks.",
        ),
        Evidence(
            "Disable telemetry issue",
            "https://github.com/anomalyco/opencode/issues/5554",
            "vendor statement",
            "OpenTelemetry support is a user-configured exporter, not an outbound channel.",
        ),
        Evidence(
            "OpenCode network guide",
            "https://voodisss.github.io/opencode-privacy-fix/",
            "independent source review",
            "Lists the CLI's outbound hosts and the disable flags at OpenCode v1.3.0.",
        ),
        Evidence(
            "Desktop bundle telemetry investigation",
            "https://stridenote.net/opencode-vs-openjarvis-telemetry/",
            "independent static inspection",
            "Reports an ungated Sentry DSN and session-health integration in desktop 1.16.2.",
        ),
    ),
)

HERMES_PROFILE = TelemetryProfile(
    key=SOURCE_HERMES,
    label="Hermes",
    default=OFF,
    summary="Shared metrics are opt-in. Update checks and model catalog fetches run by default.",
    opt_out_short="telemetry.shared_metrics.enabled/send: false",
    destinations=(
        "telemetry.nousresearch.com/v1/telemetry (opt-in shared metrics)",
        "GitHub or git remote (passive update check)",
        "models.dev (model catalog)",
        "configured LLM and tool providers",
    ),
    categories=(
        "bounded counters: activity, session length, outcomes and error classes",
        "model routes and token totals",
        "built-in tool, command and catalog names",
        "coarse machine facts such as RAM range and version age",
        "a random profile-scoped install ID in each consented package",
    ),
    content=(
        "Shared metrics never include prompts, files, paths, setting values or error text. "
        "Conversations go to the provider you configure, which is separate from telemetry."
    ),
    opt_out=(
        "telemetry.shared_metrics.enabled: false and send: false in ~/.hermes/config.yaml; "
        "updates.check: false stops passive update checks; "
        "plugins.auto_update_check_hours: 0 stops plugin checks"
    ),
    caveat=(
        "Both enabled and send must be true before anything is transmitted, and only "
        "periods fully inside a consent window are sent. Desktop update checks run on "
        "their own schedule even when updates.check is false. Older FAQ pages still "
        "claim Hermes has no telemetry."
    ),
    evidence=(
        Evidence(
            "Hermes privacy and data documentation change",
            "https://github.com/NousResearch/hermes-agent/pull/144820",
            "vendor docs",
            "Enumerates every outbound path, its default and its config key.",
        ),
        Evidence(
            "Shared metrics relay contract",
            "https://hermes-agent.nousresearch.com/docs/developer-guide/relay-shared-metrics",
            "vendor docs",
            "Documents the allowlisted package contents, consent windows and install ID scope.",
        ),
        Evidence(
            "Shared metrics setup consent text",
            "https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/setup.py",
            "vendor source",
            "Lists the exact counter categories and states what is never collected.",
        ),
    ),
)

DSH_PROFILE = TelemetryProfile(
    key=SOURCE_DSH,
    label="DeepSeek Harness",
    default=UNCLEAR,
    summary="Feedback can upload session logs. Official calls send plugin metadata and a random user ID.",
    opt_out_short="DSH_TELEMETRY_DISABLED=1",
    destinations=(
        "harness-telemetry.deepseeksvc.com/v1/logs (session telemetry)",
        "api.deepseek.com (official model calls)",
        "your configured custom model endpoints",
    ),
    categories=(
        "session log suffix on feedback with the default feedback-only composition",
        "plugin package names and versions on official DeepSeek requests",
        "optional canonical session-log suffix on official DeepSeek requests",
        "device, network, crash and performance data stated in the privacy policy",
        "a random anonymous user ID in telemetry and request headers",
    ),
    content=(
        "The shipped feedback-only mode replays full user and assistant messages, tool "
        "arguments and results, system prompts and the local session cwd. FULL mode "
        "exports projected records continuously with no shipped redaction layer."
    ),
    opt_out=(
        "DSH_TELEMETRY_DISABLED=1 or mode DISABLED; disable plugin-package-inventory-deepseek "
        "and session-log-deepseek in the active profile for official requests"
    ),
    caveat=(
        "Sources disagree on the shipped default: the documentation describes "
        "FEEDBACK_ONLY while a security discussion describes DISABLED, and the session-log "
        "plugin README and the privacy page disagree on its default. Treat the local "
        "settings below and the effective composition (dsh web --dump-config) as authoritative."
    ),
    evidence=(
        Evidence(
            "DeepSeek Harness data and privacy documentation",
            "https://deepseekdocs.com/en/docs/user-guide/privacy",
            "vendor docs",
            "Describes telemetry modes, exporter settings, the anonymous ID and egress hosts.",
        ),
        Evidence(
            "DeepSeek Harness privacy policy",
            "https://www.deepseek.com/en/harness/privacy/",
            "vendor policy",
            "States that official services collect session logs, device data and usage logs.",
        ),
        Evidence(
            "Community security discussion on FULL mode",
            "https://github.com/deepseek-ai/deepseek-harness/discussions/4100",
            "independent report",
            "Reports maximal content in FULL exports and whole-prefix release on /feedback.",
        ),
    ),
)

PROFILES: tuple[TelemetryProfile, ...] = (
    CODEX_PROFILE,
    CLAUDE_PROFILE,
    OPENCODE_PROFILE,
    HERMES_PROFILE,
    DSH_PROFILE,
)


def _env_present(name: str) -> bool:
    return name in os.environ and os.environ[name] != ""


def _env_truthy(name: str) -> bool:
    return _env_present(name) and os.environ[name].strip().lower() not in {
        "",
        "0",
        "false",
        "no",
        "off",
    }


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "not set"
    text = str(value)
    text = re.sub(r"(?i)(://)[^/@\s]+:[^/@\s]+@", r"\1***:***@", text)
    return text if len(text) <= 200 else text[:200] + "..."


def _bool_state(value: Any, *, inverted: bool = False) -> str:
    if value is None:
        return UNKNOWN
    enabled = bool(value) if isinstance(value, bool) else _display(value).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if inverted:
        enabled = not enabled
    return ON if enabled else OFF


def _hours_state(value: str | None) -> str:
    if value is None:
        return UNKNOWN
    try:
        return OFF if float(value) <= 0 else ON
    except ValueError:
        return UNKNOWN


def _setting(name: str, value: str, location: str, state: str) -> LocalSetting:
    return LocalSetting(name=name, value=value, location=location, state=state)


def _read_toml(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle), None
    except FileNotFoundError:
        return {}, "file not found"
    except (OSError, ValueError) as error:
        return {}, f"could not read: {error.__class__.__name__}"


def _strip_json_comments(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and following == "/":
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _read_json_config(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        value = json.loads(_strip_json_comments(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return {}, "file not found"
    except (OSError, ValueError) as error:
        return {}, f"could not read: {error.__class__.__name__}"
    return (value, None) if isinstance(value, dict) else ({}, "not a JSON object")


def _read_yaml_scalars(path: Path, wanted: set[str]) -> tuple[dict[str, str], str | None]:
    found: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return found, "file not found"
    except (OSError, UnicodeError) as error:
        return found, f"could not read: {error.__class__.__name__}"
    stack: list[tuple[int, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _YAML_LINE.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        key = match.group(2)
        raw = match.group(3).split(" #", 1)[0].strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        dotted = ".".join([item[1] for item in stack] + [key])
        if dotted in wanted and raw:
            found[dotted] = raw.strip("\"'")
        if not raw:
            stack.append((indent, key))
    return found, None


def _decode_b64_keys(value: str) -> set[str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.b64decode(padded, validate=False).decode("utf-8"))
    except (ValueError, UnicodeError):
        return set()
    if not isinstance(decoded, dict):
        return set()
    return {key for key in decoded if isinstance(key, str) and not _SENSITIVE_KEY.search(key)}


def _observe_claude_telemetry(home: Path) -> list[LocalObservation]:
    telemetry_dir = home / "telemetry"
    if not telemetry_dir.is_dir():
        return []
    files = sorted(telemetry_dir.glob("*.json"))
    if not files:
        return []
    event_names: set[str] = set()
    field_names: set[str] = set()
    count = 0
    truncated = False
    for path in files[:20]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines[:200]:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            data = record.get("event_data") if isinstance(record, dict) else None
            if not isinstance(data, dict):
                continue
            count += 1
            name = data.get("event_name")
            if isinstance(name, str):
                event_names.add(name)
            for key, value in data.items():
                if not _SENSITIVE_KEY.search(key):
                    field_names.add(key)
                if isinstance(value, str) and key in {"process", "additional_metadata"}:
                    field_names.update(_decode_b64_keys(value))
            if len(event_names) + len(field_names) > 80:
                truncated = True
                break
        if truncated:
            break
    if not count:
        return []
    names = ", ".join(sorted(event_names)[:12]) or "unnamed"
    fields = ", ".join(sorted(field_names)[:20]) or "unknown"
    suffix = " (sample capped)" if truncated else ""
    return [
        LocalObservation(
            "Queued telemetry events",
            f"{count} events in {len(files)} local file(s) that failed to send; event names: {names}{suffix}",
        ),
        LocalObservation(
            "Field names only",
            f"{fields}; no IDs, hashes, session IDs or device IDs were copied into this report",
        ),
    ]


def _codex_telemetry(paths: Paths) -> HarnessTelemetry:
    home = paths.codex_home
    config, read_error = _read_toml(home / "config.toml")
    analytics = config.get("analytics")
    feedback = config.get("feedback")
    otel = config.get("otel")
    analytics_value = analytics.get("enabled") if isinstance(analytics, dict) else None
    feedback_value = feedback.get("enabled") if isinstance(feedback, dict) else None
    exporter = otel.get("exporter") if isinstance(otel, dict) else None
    metrics_exporter = otel.get("metrics_exporter") if isinstance(otel, dict) else None
    prompt_logging = otel.get("log_user_prompt") if isinstance(otel, dict) else None
    settings = [
        _setting(
            "analytics.enabled",
            _display(analytics_value),
            "~/.codex/config.toml",
            _bool_state(analytics_value) if read_error is None else UNKNOWN,
        ),
        _setting(
            "feedback.enabled",
            _display(feedback_value),
            "~/.codex/config.toml",
            _bool_state(feedback_value) if read_error is None else UNKNOWN,
        ),
        _setting(
            "otel.exporter",
            _display(exporter),
            "~/.codex/config.toml",
            UNKNOWN,
        ),
        _setting(
            "otel.metrics_exporter",
            _display(metrics_exporter),
            "~/.codex/config.toml",
            UNKNOWN,
        ),
        _setting(
            "otel.log_user_prompt",
            _display(prompt_logging),
            "~/.codex/config.toml",
            _bool_state(prompt_logging) if read_error is None else UNKNOWN,
        ),
    ]
    state = _bool_state(analytics_value)
    if state == UNKNOWN:
        summary = "analytics setting not found locally (CLI default is on)"
    elif state == ON:
        summary = "built-in analytics on; opt out with [analytics] enabled = false"
    else:
        summary = "built-in analytics off in config"
    observations: list[LocalObservation] = []
    if read_error:
        observations.append(LocalObservation("Config read", read_error))
    if _bool_state(prompt_logging) == ON:
        observations.append(
            LocalObservation("Prompt logging", "otel.log_user_prompt is on; prompts go to your configured exporter")
        )
    return HarnessTelemetry(
        profile=CODEX_PROFILE,
        installed=home.is_dir(),
        local_summary=summary,
        settings=tuple(settings),
        observations=tuple(observations),
    )


def _claude_telemetry(paths: Paths) -> HarnessTelemetry:
    del paths
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser()
    disable_all = _env_present("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")
    disable_metrics = _env_present("DISABLE_TELEMETRY") or _env_present("DO_NOT_TRACK")
    disable_errors = _env_present("DISABLE_ERROR_REPORTING")
    disable_feedback = _env_present("DISABLE_FEEDBACK_COMMAND")
    settings_config, read_error = _read_json_config(home / "settings.json")
    preflight_off = settings_config.get("skipWebFetchPreflight") is True
    env_exporter = os.environ.get("OTEL_LOGS_EXPORTER")
    settings = [
        _setting(
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
            _display(os.environ.get("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC")),
            "environment",
            ON if disable_all else OFF,
        ),
        _setting("DISABLE_TELEMETRY", _display(os.environ.get("DISABLE_TELEMETRY")), "environment", ON if disable_metrics else OFF),
        _setting("DISABLE_ERROR_REPORTING", _display(os.environ.get("DISABLE_ERROR_REPORTING")), "environment", ON if disable_errors else OFF),
        _setting("DISABLE_FEEDBACK_COMMAND", _display(os.environ.get("DISABLE_FEEDBACK_COMMAND")), "environment", ON if disable_feedback else OFF),
        _setting("OTEL_LOGS_EXPORTER", _display(env_exporter), "environment", ON if env_exporter else OFF),
        _setting("skipWebFetchPreflight", _display(settings_config.get("skipWebFetchPreflight")), "~/.claude/settings.json", ON if preflight_off else OFF),
    ]
    if disable_all:
        summary = "all nonessential traffic disabled by environment"
    elif disable_metrics and disable_errors and disable_feedback:
        summary = "metrics, error reports and feedback commands disabled by environment"
    else:
        active = []
        if not disable_metrics:
            active.append("metrics")
        if not disable_errors:
            active.append("error reports")
        if not disable_feedback:
            active.append("feedback commands")
        summary = "default on for " + ", ".join(active) + " (provider-dependent)"
    return HarnessTelemetry(
        profile=CLAUDE_PROFILE,
        installed=home.is_dir(),
        local_summary=summary,
        settings=tuple(settings),
        observations=tuple(_observe_claude_telemetry(home) + ([LocalObservation("Config read", read_error)] if read_error else [])),
    )


def _opencode_telemetry(paths: Paths) -> HarnessTelemetry:
    del paths
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    config, read_error = _read_json_config(config_home / "opencode" / "opencode.jsonc")
    share = config.get("share")
    autoupdate = config.get("autoupdate")
    experimental = config.get("experimental")
    otel = experimental.get("openTelemetry") if isinstance(experimental, dict) else None
    settings = [
        _setting("OPENCODE_DISABLE_MODELS_FETCH", _display(os.environ.get("OPENCODE_DISABLE_MODELS_FETCH")), "environment", ON if _env_truthy("OPENCODE_DISABLE_MODELS_FETCH") else OFF),
        _setting("OPENCODE_DISABLE_AUTOUPDATE", _display(os.environ.get("OPENCODE_DISABLE_AUTOUPDATE")), "environment", ON if _env_truthy("OPENCODE_DISABLE_AUTOUPDATE") else OFF),
        _setting("OPENCODE_DISABLE_SHARE", _display(os.environ.get("OPENCODE_DISABLE_SHARE")), "environment", ON if _env_truthy("OPENCODE_DISABLE_SHARE") else OFF),
        _setting("share", _display(share), "~/.config/opencode/opencode.jsonc", OFF if _display(share).lower() == "disabled" else UNKNOWN),
        _setting("autoupdate", _display(autoupdate), "~/.config/opencode/opencode.jsonc", ON if autoupdate is not False else OFF),
        _setting("experimental.openTelemetry", _display(otel), "~/.config/opencode/opencode.jsonc", _bool_state(otel)),
    ]
    blocked = [
        name
        for name in ("OPENCODE_DISABLE_MODELS_FETCH", "OPENCODE_DISABLE_AUTOUPDATE", "OPENCODE_DISABLE_SHARE")
        if _env_truthy(name)
    ]
    summary = (
        "no telemetry collector configured; CLI contacts models.dev and update checks by default"
        if len(blocked) < 3
        else "known CLI background hosts disabled by environment"
    )
    observations: list[LocalObservation] = []
    if read_error and read_error != "file not found":
        observations.append(LocalObservation("Config read", read_error))
    observations.append(
        LocalObservation(
            "Desktop app",
            "no local setting for the reported Sentry path; desktop builds need a network-level block",
        )
    )
    return HarnessTelemetry(
        profile=OPENCODE_PROFILE,
        installed=(config_home / "opencode").is_dir(),
        local_summary=summary,
        settings=tuple(settings),
        observations=tuple(observations),
    )


def _hermes_telemetry(paths: Paths) -> HarnessTelemetry:
    del paths
    home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    wanted = {
        "telemetry.shared_metrics.enabled",
        "telemetry.shared_metrics.send",
        "updates.check",
        "plugins.auto_update_check_hours",
        "models_dev.url",
    }
    config, read_error = _read_yaml_scalars(home / "config.yaml", wanted)
    enabled_raw = config.get("telemetry.shared_metrics.enabled")
    send_raw = config.get("telemetry.shared_metrics.send")
    enabled = enabled_raw.lower() == "true" if enabled_raw else False
    send = send_raw.lower() == "true" if send_raw else False
    settings = [
        _setting("telemetry.shared_metrics.enabled", _display(enabled_raw), "~/.hermes/config.yaml", ON if enabled else OFF),
        _setting("telemetry.shared_metrics.send", _display(send_raw), "~/.hermes/config.yaml", ON if send else OFF),
        _setting("updates.check", _display(config.get("updates.check")), "~/.hermes/config.yaml", _bool_state(config.get("updates.check"))),
        _setting("plugins.auto_update_check_hours", _display(config.get("plugins.auto_update_check_hours")), "~/.hermes/config.yaml", _hours_state(config.get("plugins.auto_update_check_hours"))),
        _setting("models_dev.url", _display(config.get("models_dev.url")), "~/.hermes/config.yaml", UNKNOWN),
    ]
    if enabled and send:
        summary = "shared metrics collection and upload enabled in config"
    elif enabled:
        summary = "shared metrics collected locally but upload off"
    else:
        summary = "shared metrics off in config"
    observations: list[LocalObservation] = []
    if read_error and read_error != "file not found":
        observations.append(LocalObservation("Config read", read_error))
    for label, path in (
        ("Install ID", home / "install_id"),
        ("Update check cache", home / ".update_check"),
        ("Shared metrics outbox", home / "telemetry" / "shared_metrics" / "outbox"),
    ):
        if path.exists():
            observations.append(LocalObservation(label, "present locally (contents not read)"))
    return HarnessTelemetry(
        profile=HERMES_PROFILE,
        installed=home.is_dir(),
        local_summary=summary,
        settings=tuple(settings),
        observations=tuple(observations),
    )


def _dsh_telemetry(paths: Paths) -> HarnessTelemetry:
    del paths
    sessions = dsh_sessions_dir()
    home = sessions.parent if sessions.name == "sessions" else sessions
    settings = [
        _setting("DSH_TELEMETRY_DISABLED", _display(os.environ.get("DSH_TELEMETRY_DISABLED")), "environment", ON if _env_present("DSH_TELEMETRY_DISABLED") else OFF),
        _setting("DSH_TELEMETRY_MODE", _display(os.environ.get("DSH_TELEMETRY_MODE")), "environment", ON if (os.environ.get("DSH_TELEMETRY_MODE") or "").upper() in {"FULL", "FEEDBACK_ONLY"} else UNKNOWN),
        _setting("DSH_TELEMETRY_OTLP_URL", "configured" if os.environ.get("DSH_TELEMETRY_OTLP_URL") else "not set", "environment", ON if os.environ.get("DSH_TELEMETRY_OTLP_URL") else OFF),
    ]
    summary = (
        "telemetry disabled by environment"
        if _env_present("DSH_TELEMETRY_DISABLED")
        else "telemetry mode not pinned in environment; check the active profile with dsh web --dump-config"
    )
    observations: list[LocalObservation] = []
    identity = home / ".anonymous-user-id"
    if identity.exists():
        observations.append(LocalObservation("Anonymous user ID", "file present locally (value not read)"))
    if sessions.is_dir():
        observations.append(LocalObservation("Session logs", "stored locally under ~/.dsh/sessions (not read for this report)"))
    return HarnessTelemetry(
        profile=DSH_PROFILE,
        installed=home.is_dir(),
        local_summary=summary,
        settings=tuple(settings),
        observations=tuple(observations),
    )


def build_telemetry_report(paths: Paths | None = None, *, now: datetime | None = None) -> TelemetryReport:
    paths = paths or Paths.discover()
    generated_at = now or datetime.now(timezone.utc)
    return TelemetryReport(
        generated_at=generated_at,
        harnesses=[
            _codex_telemetry(paths),
            _claude_telemetry(paths),
            _opencode_telemetry(paths),
            _hermes_telemetry(paths),
            _dsh_telemetry(paths),
        ],
    )


def write_telemetry_report(report: TelemetryReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "telemetry-report.json"
    markdown_path = output_dir / "telemetry-report.md"
    json_path.write_text(report.to_json(), encoding="utf-8")
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return json_path, markdown_path
