# codex-stats

`codex-stats` is a local analytics CLI for Codex usage.

It reads your local Codex state from `~/.codex` and surfaces:

- session summaries
- rolling usage totals across today, week, month, or the last `N` days
- model and project breakdowns
- project-specific drilldowns
- recent session history
- estimated token-based cost
- anomaly-aware usage insights and recommendations
- export and import for cross-device snapshots
- merged export snapshots for multi-device rollups
- OTLP metrics export for Grafana and OpenTelemetry collectors
- shareable weekly and monthly reports

## Install

```bash
pipx install codex-stats
```

Or with `pip`:

```bash
python3 -m pip install codex-stats
```

## Command Reference

- `codex-stats`
  Show the default usage summary for today.
- `codex-stats today`
  Show today's usage summary explicitly.
- `codex-stats week`
  Show usage totals for the last 7 days.
- `codex-stats month`
  Show usage totals for the last 30 days.
- `codex-stats --days 14`
  Show a rolling summary for the last `N` days.
- `codex-stats session`
  Show the most recent session in detail.
- `codex-stats session --id <session_id>`
  Show one specific session by ID.
- `codex-stats models`
  Break usage down by model.
- `codex-stats project`
  Break usage down by project.
- `codex-stats project backend-api`
  Show a single project's summary across all available local data.
- `codex-stats project backend-api --days 30`
  Show a single project's summary for a rolling time window.
- `codex-stats daily`
  Show per-day usage with an ASCII trend graph.
- `codex-stats compare`
  Compare the last 7 days against the previous 7 days.
- `codex-stats compare today yesterday`
  Compare named time windows directly.
- `codex-stats history`
  Show recent session history.
- `codex-stats top`
  Show the largest sessions by token usage.
- `codex-stats top --project backend-api`
  Show the largest sessions for one project.
- `codex-stats costs`
  Show estimated cost totals and monthly projection.
- `codex-stats insights`
  Show anomaly-aware insights and recommended next steps.
- `codex-stats doctor`
  Validate local Codex data sources and config.
- `codex-stats doctor --strict`
  Return a non-zero exit code if any doctor check fails.
- `codex-stats init`
  Create a default config file under `~/.config/codex-stats/`.
- `codex-stats config show`
  Show the effective config, including pricing and display defaults.
- `codex-stats report weekly`
  Generate a weekly shareable report.
- `codex-stats report weekly --format markdown`
  Generate a weekly report in Markdown.
- `codex-stats report weekly --format html`
  Generate a standalone HTML report for sharing, including inline charts.
- `codex-stats report weekly --format svg`
  Generate a bundle of four smaller standalone SVG assets in the current working directory: summary, cost, focus, and project snapshots.
- `codex-stats report weekly --project backend-api`
  Generate a weekly report for one project.
- `codex-stats report weekly --format markdown --output weekly-report.md`
  Write a formatted report to a file.
- `codex-stats report weekly --format html --output weekly-report.html`
  Write a polished standalone HTML report to a file.
- `codex-stats report weekly --format svg --output weekly-report-assets`
  Write the SVG asset bundle into the output directory you provide.
- `codex-stats report weekly --format html --render`
  Generate an HTML report, write it to a temp file, and open it in the default browser.
- `codex-stats report weekly --format svg --render`
  Generate an SVG report, write it to a temp file, and open it in the default browser.
- `codex-stats export codex-stats-export.json`
  Export normalized local stats to JSON.
- `codex-stats export codex-stats-export.json --since 30d`
  Export only a rolling window of recent sessions.
- `codex-stats import laptop.json desktop.json`
  Read one or more exported snapshots and summarize them.
- `codex-stats merge merged.json laptop.json desktop.json`
  Merge multiple exported snapshots into one deduplicated file.
- `codex-stats merge merged.json laptop.json desktop.json --json`
  Merge snapshots and return a machine-readable merge summary.
- `codex-stats otel --output otlp-metrics.json`
  Write OTLP JSON metrics derived from local Codex session data.
- `codex-stats otel --endpoint http://localhost:4318/v1/metrics`
  Push OTLP JSON metrics directly to an OTLP/HTTP collector endpoint.
- `codex-stats otel --since 30d --daily-days 14 --resource-attr deployment.environment=dev`
  Export a rolling window plus daily history with additional resource metadata.
- `codex-stats watch`
  Run a live terminal dashboard that refreshes usage summaries continuously.
- `codex-stats watch --project backend-api --days 14 --interval 2`
  Watch one project with a shorter refresh interval and a custom rolling window.
- `codex-stats watch --alert-cost-usd 20 --alert-tokens 500000 --alert-delta-pct 50`
  Raise live alerts when the rolling window crosses your chosen thresholds.
- `codex-stats watch --reset-state`
  Ignore the saved watch baseline for this scope and rebuild it from the current snapshot.
- `codex-stats completions zsh`
  Print shell completion setup for your shell.
- `codex-stats --color always`
  Force ANSI color output.
- `codex-stats --json`
  Return machine-readable JSON output for supported commands.

## How It Works

`codex-stats` does not proxy or intercept Codex API traffic.

It reads local Codex artifacts, including:

- `state_5.sqlite` for session metadata
- rollout JSONL files for request and token snapshots

## Notes

- Costs are estimates, not billing values.
- Output depends on local Codex file formats remaining compatible.
- `export` and `import` let you move normalized snapshots between machines.
- `merge` lets you deduplicate and combine exported snapshots into one file.
- `export --since Nd` limits snapshots to a rolling window before sharing.
- `otel` emits OTLP/HTTP JSON metrics, including aggregate token counters and daily historical gauges.
- `watch` is intended for interactive terminals and exits cleanly on `Ctrl-C`.
- `watch` persists alert/session baseline state under the config directory so `NEW` markers survive restarts unless you pass `--reset-state`.
- `doctor --strict` is useful in scripts and CI because it returns a non-zero exit code on failed checks.
- `--color auto|always|never` controls ANSI styling.

## OpenTelemetry Export

The `otel` command converts local Codex session data into OTLP JSON metrics so you can feed them into Grafana, Grafana Alloy, or any OTLP/HTTP collector.

Write the payload to disk:

```bash
codex-stats otel --output otlp-metrics.json
```

Push directly to an OTLP/HTTP endpoint:

```bash
codex-stats otel --endpoint http://localhost:4318/v1/metrics
```

Add resource metadata or restrict the export window:

```bash
codex-stats otel \
  --since 30d \
  --daily-days 14 \
  --resource-attr deployment.environment=dev \
  --resource-attr service.namespace=developer-tools
```

Exported metrics include aggregate sums such as `codex_stats_tokens`, `codex_stats_requests`, and `codex_stats_estimated_cost_usd`, plus daily gauges such as `codex_stats_daily_tokens`.

## Grafana Starter Kit

This repo now includes starter assets under [examples/grafana/codex-stats-dashboard.json](/Users/vivek/Desktop/Salad/codex_stats/examples/grafana/codex-stats-dashboard.json) and [examples/grafana/grafana-alloy.alloy](/Users/vivek/Desktop/Salad/codex_stats/examples/grafana/grafana-alloy.alloy).

Quick local loop:

```bash
alloy run examples/grafana/grafana-alloy.alloy
codex-stats otel --endpoint http://localhost:4318/v1/metrics --since 30d
```

Then import the dashboard JSON into Grafana and point it at your Prometheus-compatible datasource. The dashboard includes:

- topline stats for tokens, requests, sessions, and estimated cost
- daily token, request, and cost charts
- table views for token usage by project and estimated cost by model

## Roadmap

The current priority list lives in [docs/roadmap.md](/Users/vivek/Desktop/Salad/codex_stats/docs/roadmap.md).

## Shareable Assets

Share-ready assets now live under [docs/assets/codex-stats-share-card.svg](/Users/vivek/Desktop/Salad/codex_stats/docs/assets/codex-stats-share-card.svg), and `report --format svg` can generate a full bundle of report assets directly from local usage data.

## Watch Alerts

`watch` can surface live warnings and critical alerts directly in the terminal dashboard.

Example:

```bash
codex-stats watch \
  --days 7 \
  --alert-cost-usd 20 \
  --alert-tokens 500000 \
  --alert-requests 20 \
  --alert-delta-pct 50
```

Alerts currently cover:

- explicit cost, token, request, and delta thresholds
- large usage spikes versus the previous window
- anomaly conditions already detected by the insights engine
- stateful marking of newly triggered conditions and newly observed sessions across watch restarts for the same scope

## Pricing Config

Optional pricing config lives at `~/.config/codex-stats/config.toml`.

```toml
[pricing]
default_usd_per_1k_tokens = 0.01

[pricing.model_usd_per_1k_tokens]
gpt-5.4 = 0.02
gpt-5-mini = 0.005
```

To create the config file automatically:

```bash
codex-stats init
```

To inspect the effective config:

```bash
codex-stats config show
codex-stats config show --json
```

## JSON Schemas

Machine-readable output is intended to stay stable across patch releases.

- `summary` JSON: time-window totals such as sessions, requests, tokens, cost estimate, and top model
- `report` JSON: period, optional project scope, summary, comparison, projects, top sessions, costs, and insights
- `export` JSON: `schema_version`, `exported_at`, and normalized `sessions`
- `doctor` JSON: a list of checks with `name`, `ok`, `detail`, and `severity`
- `config` JSON: config path, whether the file exists, pricing defaults, overrides, and display defaults
- `import` and `merge` JSON: import summary plus deduped session counts

Full field documentation lives in [docs/json-schema.md](/Users/vivek/Desktop/Salad/codex_stats/docs/json-schema.md).

## Development

For local development from the repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools
python -m pip install -e .
```

Run without installing:

```bash
PYTHONPATH=src python3 -m codex_stats
```
