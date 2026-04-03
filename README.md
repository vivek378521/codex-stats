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
- shareable weekly and monthly reports

## Install

```bash
pipx install codex-stats
```

Or with `pip`:

```bash
python3 -m pip install codex-stats
```

## Commands

```bash
codex-stats
codex-stats today
codex-stats week
codex-stats month
codex-stats session
codex-stats session --id <session_id>
codex-stats models
codex-stats project
codex-stats project backend-api
codex-stats project backend-api --days 30
codex-stats daily
codex-stats compare
codex-stats compare today yesterday
codex-stats history
codex-stats top
codex-stats top --project backend-api
codex-stats costs
codex-stats insights
codex-stats doctor
codex-stats doctor --strict
codex-stats init
codex-stats report weekly
codex-stats report weekly --format markdown
codex-stats report weekly --project backend-api
codex-stats report weekly --format markdown --output weekly-report.md
codex-stats --days 14
codex-stats --color always
codex-stats export codex-stats-export.json
codex-stats export codex-stats-export.json --since 30d
codex-stats import laptop.json desktop.json
codex-stats merge merged.json laptop.json desktop.json
codex-stats completions zsh
codex-stats --json
```

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
- `doctor --strict` is useful in scripts and CI because it returns a non-zero exit code on failed checks.
- `--color auto|always|never` controls ANSI styling.

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
