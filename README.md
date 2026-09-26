# codex-stats

`codex-stats` is a local analytics tool for coding agents.

It reads local session data from every coding assistant installed on the machine and surfaces:

- a browser dashboard with an **Overview** tab for every tool combined, plus one tab per tool (Codex, OpenCode, Claude Code, Hermes)
- day, week, month, and all-time windows inside every tab
- model and project breakdowns
- recent session history
- estimated token-based cost (or each tool's own recorded cost when available)
- per-tool cost overrides and a stacked per-tool token trend on the Overview
- anomaly-aware usage insights and recommendations
- file-level impact tracking: a "Most Edited Files" panel showing per-file edit counts and add/delete line totals parsed from Codex and Claude Code rollouts
- shareable JPG cards and browser PDF export from the dashboard

## Data Sources

Every tool below always gets a tab, whether or not local data exists. Tools with no
sessions render an empty state instead of being hidden.

| Tool | Location | Notes |
| --- | --- | --- |
| Codex | `~/.codex` | `state_5.sqlite` + rollout JSONL files |
| OpenCode | `~/.local/share/opencode/opencode.db` | recorded cost + tokens per session |
| Claude Code | `~/.claude/projects/**/*.jsonl` | per-project transcripts |
| Hermes | `~/.hermes/state.db` | recorded cost + tokens per session |

Use these environment variables to point at non-default locations (also used for test isolation):

- `CODEX_HOME` (Codex), `CODEX_STATS_OPENCODE_HOME` (OpenCode),
  `CODEX_STATS_CLAUDE_PROJECTS_DIR` (Claude), `CODEX_STATS_HERMES_HOME` (Hermes)

## Install

```bash
pipx install codex-stats
```

Or with `pip`:

```bash
python3 -m pip install codex-stats
```

## Command Reference

There is exactly one command, and it takes no options:

```bash
codex-stats
```

It reads local session data, writes a standalone dashboard HTML file to a temporary
path, and opens it in your default browser.

Inside the dashboard, use the action bar to:

- switch tools with the **Overview / Codex / OpenCode / Claude Code / Hermes** tab row
- switch between `Day`, `Week`, `Month`, and `All Time` inside the active tool
- print the active tool and window to PDF
- download shareable JPG cards for summary, cost, focus, and project share

## How It Works

`codex-stats` does not proxy or intercept API traffic. It reads local artifacts:
Codex `state_5.sqlite` and rollout files, the OpenCode database, Claude Code project
transcripts, and the Hermes database, then normalizes everything into one session model.

## Notes

- When a tool records its own cost (OpenCode, Hermes), that recorded value wins for the
  session and no estimate is used.
- Otherwise cost is priced **per token component**, because cached reads and output are
  not the same price as fresh input. Every session is normalized to four buckets:
  fresh input, cache reads, cache writes, and output.
- Providers disagree on how they report cache reads. OpenAI (Codex) counts them *inside*
  `input_tokens`; Anthropic (Claude) reports them *separately*. `codex-stats` normalizes
  both conventions at ingest, so the cache ratio is always a real fraction between 0 and 1
  and the four components always sum to the provider's own total.
- A default rate table ships for known models, taken from each provider's published
  pricing page and converted from USD per million tokens to USD per 1k. It is a **dated
  snapshot**: see `RATE_SNAPSHOT_DATE` and `RATE_SNAPSHOT_SOURCES` in
  `src/codex_stats/config.py`, and update it when published prices move.
  - OpenAI rates are standard processing, short context. OpenAI only bills explicit cache
    writes from GPT-5.6 onward; earlier models use implicit caching, so their cache-write
    rate is 0. Long-context (>272k) pricing is not modeled.
  - Anthropic rates are standard pricing with 5-minute cache writes (1.25x base input).
    1-hour writes (2x), Batch (-50%), fast mode, and the 1.1x data-residency multiplier
    are not modeled.
  - Model names are matched exactly first, then with a provider prefix stripped, so
    `anthropic/claude-opus-4.6` resolves to the same rates as `claude-opus-4.6`.
- Any model that cannot be identified — most often a third-party alias such as a
  provider's internal codename — falls back to `DEFAULT_FALLBACK_RATES`, a mid-tier
  published rate rather than a flat rate. A flat fallback badly overestimates
  cache-heavy sessions, because cache reads are normally about 10x cheaper than fresh
  input. The dashboard labels these sessions ("N sessions on a fallback rate") rather
  than presenting a silently wrong number. Set `default_usd_per_1k_tokens` to use a
  single flat rate for them instead.
- Override rates per model in `~/.config/codex-stats/config.toml`:

  ```toml
  [pricing]
  # optional: replace the fallback for unidentifiable models with one flat rate
  # default_usd_per_1k_tokens = 0.003

  [pricing.model_usd_per_1k_tokens.gpt-5.4]
  input = 0.0025
  cached_read = 0.00025
  cache_write = 0.0
  output = 0.015

  # a single scalar still works and applies to all four components
  [pricing.model_usd_per_1k_tokens]
  some-alias-model = 0.004

  # a source rate overrides the model table
  [pricing.source_usd_per_1k_tokens]
  claude = 0.015
  ```

- Output depends on local file formats remaining compatible.

## Roadmap

The current priority list lives in [docs/roadmap.md](https://github.com/vivek378521/codex-stats/blob/main/docs/roadmap.md).

## Shareable Assets

The dashboard exports JPG cards with names like:

- [docs/assets/codex-stats-week-summary-card.jpg](https://github.com/vivek378521/codex-stats/blob/main/docs/assets/codex-stats-week-summary-card.jpg)
- [docs/assets/codex-stats-week-cost-card.jpg](https://github.com/vivek378521/codex-stats/blob/main/docs/assets/codex-stats-week-cost-card.jpg)
- [docs/assets/codex-stats-week-focus-card.jpg](https://github.com/vivek378521/codex-stats/blob/main/docs/assets/codex-stats-week-focus-card.jpg)
- [docs/assets/codex-stats-week-projects-card.jpg](https://github.com/vivek378521/codex-stats/blob/main/docs/assets/codex-stats-week-projects-card.jpg)

These sample assets were generated from the current renderer so the docs match what the dashboard actually downloads.

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
