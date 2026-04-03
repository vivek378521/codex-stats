# codex-stats

Local AI usage observability CLI for Codex sessions.

## What it does

`codex-stats` reads local Codex state from `~/.codex` and shows:

- session totals from `state_5.sqlite`
- request counts from rollout JSONL files
- model and project breakdown from local session metadata
- estimated cost from a local pricing table

## Install

```bash
pip install .
```

After publish:

```bash
pipx install codex-stats
```

For local development:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools
python -m pip install -e .
```

## Usage

```bash
codex-stats
codex-stats today
codex-stats session
codex-stats session --id <session_id>
codex-stats --json
```

From the repo without installing:

```bash
PYTHONPATH=src python3 -m codex_stats
```

## Notes

- This tool does not intercept Codex API traffic.
- Costs are estimates, not authoritative billing values.
- The current MVP relies on local file formats that may evolve with Codex CLI versions.

## Release

Recommended publish flow:

1. Create a GitHub repository and replace the placeholder URLs in `pyproject.toml`.
2. Create a PyPI project named `codex-stats`.
3. Configure PyPI Trusted Publishing for the GitHub repository.
4. Push a version tag and publish a GitHub release.
5. The release workflow will build and upload the package to PyPI.
