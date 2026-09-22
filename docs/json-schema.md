# JSON Schemas

`codex-stats` exposes one stable JSON-oriented structure for automation: the
normalized export written by `codex-stats export`.

## Export

Used by:

- `codex-stats export stats.json`
- `codex-stats export stats.json --since 30d`

Top-level fields:

- `schema_version` — currently `1`
- `exported_at` — ISO-8601 timestamp of when the export was written
- `sessions` — list of normalized session records, sorted newest first

Each `session` entry contains the normalized local session metadata plus
rollout-derived token and cost data:

- `session`
  - `session_id`
  - `created_at` — ISO-8601
  - `updated_at` — ISO-8601
  - `cwd` — working directory the session ran in
  - `project_name` — derived from the session's working directory
  - `model` — model name, or `null`
  - `model_provider`
  - `tokens_used` — token count recorded by the tool itself
  - `rollout_path`
  - `git_branch` — or `null`
  - `git_origin_url` — or `null`
  - `source` — `codex`, `opencode`, `claude`, or `hermes`
- `request_count`
- `input_tokens` — or `null`
- `output_tokens` — or `null`
- `cached_input_tokens` — or `null`
- `reasoning_output_tokens` — or `null`
- `total_tokens_from_rollout` — or `null`
- `effective_total_tokens` — the best available total token count for the session
- `started_at` — ISO-8601, or `null`
- `recorded_cost_usd` — the tool's own recorded cost when available, else `null`
- `file_edits` — normalized file-level edits captured from Codex and Claude Code rollouts (empty for OpenCode/Hermes and for sessions with no logged file tool). Each entry has:
  - `path` — file path touched by the edit
  - `action` — `created`, `updated`, or `deleted`
  - `insertions` — lines added by the edit
  - `deletions` — lines removed by the edit

`--since Nd` limits the export to a rolling window of recent sessions (for
example `--since 30d` for the last 30 days).

### Example

```json
{
  "schema_version": 1,
  "exported_at": "2026-09-22T10:00:00+00:00",
  "sessions": [
    {
      "session": {
        "session_id": "abc123",
        "created_at": "2026-09-21T14:03:11+00:00",
        "updated_at": "2026-09-21T14:47:02+00:00",
        "cwd": "/Users/dev/my-project",
        "project_name": "my-project",
        "model": "gpt-5.4",
        "model_provider": "openai",
        "tokens_used": 223342,
        "rollout_path": "~/.codex/sessions/2026/09/21/rollout-abc123.jsonl",
        "git_branch": "main",
        "git_origin_url": "git@github.com:dev/my-project.git",
        "source": "codex"
      },
      "request_count": 6,
      "input_tokens": 250,
      "output_tokens": 30,
      "cached_input_tokens": 50,
      "reasoning_output_tokens": 7,
      "total_tokens_from_rollout": 280,
      "effective_total_tokens": 280,
      "started_at": "2026-09-21T14:03:09+00:00",
      "recorded_cost_usd": null,
      "file_edits": [
        {
          "path": "src/main.py",
          "action": "updated",
          "insertions": 1,
          "deletions": 1
        }
      ]
    }
  ]
}
```