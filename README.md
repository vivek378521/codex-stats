# codex-stats

`codex-stats` is a local analytics CLI for Codex usage.

It reads your local Codex state from `~/.codex` and surfaces:

- session summaries
- rolling usage totals across today, week, month, or the last `N` days
- model and project breakdowns
- recent session history
- estimated token-based cost
- basic usage insights
- export and import for cross-device snapshots

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
codex-stats daily
codex-stats compare
codex-stats history
codex-stats costs
codex-stats insights
codex-stats doctor
codex-stats --days 14
codex-stats --color always
codex-stats export codex-stats-export.json
codex-stats import codex-stats-export.json
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
- `--color auto|always|never` controls ANSI styling.

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
