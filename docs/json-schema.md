# JSON Schemas

`codex-stats` exposes stable JSON-oriented structures for automation.

## Summary

Used by:

- `codex-stats --json`
- `codex-stats today --json`
- `codex-stats week --json`
- `codex-stats month --json`
- `codex-stats project <name> --json`

Fields:

- `label`
- `sessions`
- `requests`
- `input_tokens`
- `output_tokens`
- `cached_input_tokens`
- `reasoning_output_tokens`
- `total_tokens`
- `estimated_cost_usd`
- `top_model`
- `average_tokens_per_request`
- `cache_ratio`
- `largest_session_tokens`

## Report

Used by:

- `codex-stats report weekly --format json`
- `codex-stats report monthly --format json`

Fields:

- `period`
- `project_name`
- `summary`
- `comparison`
- `projects`
- `top_sessions`
- `costs`
- `insights`

## Export

Used by:

- `codex-stats export stats.json`

Fields:

- `schema_version`
- `exported_at`
- `sessions`

Each `session` entry contains normalized local session metadata plus rollout-derived token counts.

## Doctor

Used by:

- `codex-stats doctor --json`

Fields:

- `checks`

Each check includes:

- `name`
- `ok`
- `detail`
- `severity`

`severity` is currently one of:

- `error`
- `warning`

## Config

Used by:

- `codex-stats config show --json`

Fields:

- `config_path`
- `exists`
- `pricing_default_usd_per_1k_tokens`
- `pricing_model_overrides`
- `display`

`display` contains:

- `color`
- `history_limit`
- `compare_days`

## Import

Used by:

- `codex-stats import a.json b.json --json`

Fields:

- `import_summary`
- `summary`
- `models`
- `projects`
- `history`
- `top`
- `costs`
- `insights`

`import_summary` contains:

- `files_read`
- `sessions_loaded`
- `duplicates_removed`
- `merged_sessions`
- `oldest_session_at`
- `newest_session_at`

## Merge

Used by:

- `codex-stats merge merged.json a.json b.json --json`

Fields:

- `output_path`
- `import_summary`
