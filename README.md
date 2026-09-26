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

- Costs are estimates by default. When a tool records its own cost (OpenCode, Hermes),
  that value wins for the session. Per-tool rates can be set in `~/.config/codex-stats/config.toml`:

  ```toml
  [pricing.source_usd_per_1k_tokens]
  codex = 0.01
  opencode = 0.01
  claude = 0.015
  hermes = 0.008
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
