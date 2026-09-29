# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Agent behavior tracking: a **Tool Behavior** panel in every window that shows
  what the agents actually did, not just what they cost. It reads tool calls
  from Codex rollouts, Claude Code transcripts, the OpenCode `part` table, and
  the Hermes message log, and normalizes every CLI's tool vocabulary into shared
  categories (Read, Edit, Execute, Search, Web, Subagent, Plan, Other) so the
  Overview aggregates all tools on one scale.
- Failure rate per tool and per category. OpenCode and Claude Code record status
  explicitly; Codex has no per-call status, so its detector trusts only
  structured headers (`Script failed`, `apply_patch verification failed`) and
  `Exit code:`, making Codex errors a conservative lower bound.
- Repeated-call detection: calls are fingerprinted from their identity-bearing
  arguments, and repeats are counted within a single session, so `1,718 calls
  repeated work already done in the same session (26% of all calls)` is now a
  measured number instead of a guess.
- Read/write ratio and abandoned-turn counts, surfaced both in the panel KPIs
  and as takeaways that outrank the heuristic cost advice when space is tight.
- Repeated-call time: repeat instances are timestamped where the source records
  durations (OpenCode, Claude Code), so the panel reports what share of
  tool-call time went to repeat work. On real data this reframes raw counts —
  one source shows 32% of calls repeated but only 10% of tool time, because the
  repeats are cheap ops.
- Failure recovery: a failed call that is later retried to success in the same
  session counts as recovered. The panel shows recovered-failure counts per
  tool, and takeaways call out failures that were never resolved
  (e.g. "Only 30% of 20 tool failures were retried to success in-session"). The
  panel notes that recovery is an exact command match, so a retry that changes
  the command still counts as unresolved.
- Claude Code no longer reads its session-control tools (`AskUserQuestion`,
  `ExitPlanMode`) as failures: a dismissed question or rejected plan is
  interaction noise, not a tool error.

## [1.10.0] - 2026-09-27

### Added
- Optional leaderboard submission straight from the dashboard. Totals are
  computed locally and signed before upload; the browser only ever sends a
  username. The endpoint and signing key are baked in, so a fresh install can
  submit with no configuration.
- `CODEX_STATS_DISABLE_LEADERBOARD` to opt out. Submitting publishes a username
  and token totals to a third-party server, so refusing it has to stay possible.
- `CODEX_STATS_LEADERBOARD_URL` and `CODEX_STATS_LEADERBOARD_KEY` to override the
  baked-in defaults, which is what allows the key to be rotated without cutting a
  release.
- A public hash-chained audit log on the leaderboard, so edits to past
  submissions are detectable.

### Changed
- Packaging metadata expanded for discoverability: a fuller description, broader
  keywords, and additional Trove classifiers including
  `Topic :: System :: Monitoring` and `Typing :: Typed`.
- License metadata moved to the SPDX form (PEP 639) and the deprecated
  `license = { text = ... }` table dropped. The License classifier is removed
  because setuptools rejects having both.
- Minimum build requirement raised to `setuptools>=77` for SPDX license support.

### Fixed
- Six `tmp-*` scratch files from local dashboard previews were tracked in git and
  would have shipped inside the source distribution. They are removed and now
  ignored.

## [1.9.0]

- Prior release. See the commit history for detail.
