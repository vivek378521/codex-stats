# codex-stats

Local analytics for coding agents. `codex-stats` reads the session data already on
your machine from Codex, OpenCode, Claude Code, Hermes, and DeepSeek Harness, then
writes a standalone browser dashboard.

## What you get

- An **Overview** tab plus one tab per tool, each with day, week, month, and all-time windows
- A **Graphs / Stats** toggle: charts first, or numbers and tables first
- Token, cost, model, project, branch, and provider breakdowns
- Session outcomes, context hygiene, tool behavior, and MCP/skill/subagent attribution
- Efficiency (cost per 1k lines), waste ledger with the Context Tax flow diagram to show
  where spend goes, leaks, runway/burn, and regression detection
- Animated donuts, columns, treemaps, gauges, scatter plots, calendars, stacked areas, and heatmaps
- Shareable JPG cards and browser PDF export
- A cited telemetry/privacy panel: what each harness sends, where, and how to turn it off

## Install

```bash
pipx install codex-stats
```

Or with pip:

```bash
python3 -m pip install codex-stats
```

## Run

```bash
codex-stats
```

It writes `~/.cache/codex-stats/dashboard.html` and opens it in your browser. Set
`XDG_CACHE_HOME` to move it. Inside the dashboard, use the tab row to switch tools and
windows, the **Graphs / Stats** toggle to switch views, the search box to filter rows,
**Data sources** to inspect ingest health, **Telemetry and privacy** to see what each
harness sends off the machine, and the export menu for PDF and JPG cards.
Press `G` or `S` anywhere outside a text field to switch between Graphs and Stats.

## Data sources

| Tool | Location | Notes |
| --- | --- | --- |
| Codex | `~/.codex` | `state_5.sqlite` + rollout JSONL, including git branch |
| OpenCode | `~/.local/share/opencode/opencode.db` | recorded cost + tokens per session |
| Claude Code | `~/.claude/projects/**/*.jsonl` | per-project transcripts, including git branch |
| Hermes | `~/.hermes/state.db` | recorded cost + tokens per session |
| DeepSeek Harness | `~/.dsh/sessions` | zstd JSONL event logs: tokens, tool calls, file edits |

Override locations with `CODEX_HOME`, `CODEX_STATS_OPENCODE_HOME`,
`CODEX_STATS_CLAUDE_PROJECTS_DIR`, `CODEX_STATS_HERMES_HOME`, and
`CODEX_STATS_DSH_HOME`.

Each source reads its 2,000 most recent sessions by default. Set
`CODEX_STATS_MAX_SESSIONS=N` to change the cap, or `0` to read everything. Parsed
sessions are cached under the dashboard cache directory and re-read when a source
changes.

## Telemetry disclosure

The dashboard's **Telemetry and privacy** panel is collapsed by default. It shows, for
each harness, its default behavior, destinations, data categories, whether prompts or
code are included, the exact opt-out, and caveats. Curated claims link to vendor docs,
vendor source, or independent source review and carry a review date; the local settings
underneath are read from this machine only and take precedence. Use the panel's buttons
to download the report as JSON or Markdown.

You can also write both files from the terminal:

```bash
codex-stats --telemetry-report
```

They land in `~/.cache/codex-stats/telemetry-report.json` and `telemetry-report.md`, and
the command prints a short summary. **`codex-stats` never uploads this report anywhere.**
For Claude Code, the panel reports event and field *names* from locally queued
failed-send telemetry files; IDs, hashes, device IDs, and session IDs are excluded.

## Cost

Cost is estimated per token component (fresh input, cache reads, cache writes, output)
from a dated rate snapshot. OpenCode and Hermes recorded costs win when present. Update
rates or set a monthly budget in `~/.config/codex-stats/config.toml`:

```toml
[pricing.model_usd_per_1k_tokens.gpt-5.4]
input = 0.0025
cached_read = 0.00025
cache_write = 0.0
output = 0.015

[budget]
monthly_limit_usd = 120.0
warn_at_ratio = 0.9
```

Unidentified models use a labeled mid-tier fallback rather than a flat rate.

## Leaderboard

The leaderboard is opt-in. With `CODEX_STATS_ENABLE_LEADERBOARD=1`, the tool can submit
your all-time totals (tokens, requests, sessions, estimated cost, and per-CLI token
share) under a username you choose. Prompts, file names, project names, models, and
timestamps are never sent. Use `CODEX_STATS_DISABLE_LEADERBOARD=1` to hard-disable it,
or `CODEX_STATS_LEADERBOARD_URL` to point at your own server.

## Notes

- Projects are identified by working directory, not folder name alone.
- Branches are grouped per repository; a branch idle for 14 days is flagged as quiet.
- Outcomes are conservative: "verified" requires a successful test, lint, typecheck, or
  build after the final edit. Unsupported signals stay unclassified.
- Waste and per-line costs are labeled estimates, not invoices.
- When history is truncated, the dashboard says so rather than reporting a partial
  history as complete.

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .

PYTHONPATH=src python3 -m codex_stats
PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff check src tests
mypy src/codex_stats
```

The roadmap lives in [docs/roadmap.md](docs/roadmap.md).
