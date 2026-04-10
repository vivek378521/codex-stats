# codex-stats

`codex-stats` is a local analytics tool for Codex usage.

It reads your local Codex state from `~/.codex` and surfaces:

- a browser dashboard with day, week, month, and all-time tabs
- model and project breakdowns
- recent session history
- estimated token-based cost
- anomaly-aware usage insights and recommendations
- export for cross-device snapshots
- shareable JPG cards and browser PDF export from the dashboard

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
  Generate a standalone dashboard HTML file and open it in the default browser.
- `codex-stats --output codex-stats-dashboard.html`
  Write the dashboard HTML to a fixed path.
- `codex-stats --output codex-stats-dashboard.html --no-open`
  Write the dashboard HTML without opening the browser.
- `codex-stats export codex-stats-export.json`
  Export normalized local stats to JSON.
- `codex-stats export codex-stats-export.json --since 30d`
  Export only a rolling window of recent sessions.

Inside the dashboard, use the action bar to:

- switch between `Day`, `Week`, `Month`, and `All Time`
- print the active tab to PDF
- download shareable JPG cards for summary, cost, focus, and project share

## How It Works

`codex-stats` does not proxy or intercept Codex API traffic.

It reads local Codex artifacts, including:

- `state_5.sqlite` for session metadata
- rollout JSONL files for request and token snapshots

## Notes

- Costs are estimates, not billing values.
- Output depends on local Codex file formats remaining compatible.
- `export --since Nd` limits snapshots to a rolling window before sharing.

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
