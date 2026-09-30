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
- Bounded history read so startup no longer scales without limit. Reading a
  session means parsing its rollout or transcript line by line, and that cost is
  linear in total history on every launch: measured on synthetic histories at 20
  tool calls per session, 400 sessions took 2.6s to build and 3,200 took 9.2s,
  with peak memory growing from 52MB to 71MB. Each source now reads only the
  2,000 most recent sessions, which caps that work: the same 3,200-session
  history drops to 5.8s. Set `CODEX_STATS_MAX_SESSIONS=0` to read everything for
  exact figures. On a machine with 88 sessions the bound never applies and
  startup is unchanged at 0.5s.
- A visible disclosure whenever the bound drops history, because a truncated
  history silently reported as the whole one is worse than a slow dashboard. A
  "Partial history" note sits above the tabs, stating how many of how many
  sessions were read and how to read them all, so it qualifies every number on
  the page whichever tab is open.
- The history cap is applied newest-first, so the windows closest to today
  degrade last. It is a bound on cost, not a guarantee that every window is
  exact: a user running 2,000 sessions in a single day will still have their
  "Last 30 Days" cut short, since session count does not predict how much time a
  history spans.

### Changed
- File-level impact moved from the main page into the per-project drilldowns. A
  window-wide "Most Edited Files" panel repeated the same paths in every tab and
  was empty for OpenCode and Hermes scopes, which never record file edits, so it
  now renders as a "Most Edited Files in This Project" table inside each project
  drilldown, where the path actually carries meaning. Aggregation, the
  window-level takeaway, and the copy summary are unchanged.
- The dashboard now lands on the narrowest window that can actually show a
  trend, instead of always opening on Today. A single day cannot draw the trend
  line, so a Today landing spent the whole first screen on empty states ("No
  trend yet", "Nothing to rank yet", "No activity map yet") and read as broken
  rather than new. On a machine with 3 sessions today and 13 across 5 days, the
  page now opens on Last 7 Days. Today is still one click away, and a workspace
  with no recorded history at all still opens on the first tab.
- Removed nine duplicated figures from a single screen, taking the KPI tiles per
  window from 22 to 12 without dropping any information. The peak weekday and
  peak hour appeared three times (summary badges, the Work Rhythm sentence, and
  a meta line); the window cost and token totals appeared in the hero and again
  in the Comparison and Costs panels, with the Costs panel repeating the hero's
  own total under a different label; and the Comparison and Costs panels each
  showed a delta that the hero had already led with. Average alongside median
  session length, and mean alongside median requests per session, were the same
  statistic twice.

## [1.10.0] - 2026-09-27

### Added
- Optional private-leaderboard submission straight from the dashboard. Totals
  are computed locally and signed before upload; the browser only ever sends a
  username. It requires an operator-configured endpoint and key.
- `CODEX_STATS_DISABLE_LEADERBOARD` to opt out. Submitting publishes a username
  and token totals to a third-party server, so refusing it has to stay possible.
- `CODEX_STATS_LEADERBOARD_URL` and `CODEX_STATS_LEADERBOARD_KEY` to configure a
  private submission endpoint.
- A public hash-chained audit log on the leaderboard, so edits to past
  submissions are detectable.

### Security

- Disabled public leaderboard submission. The former package-wide HMAC key was
  public to every installation, allowing forged token totals. A total computed
  from locally controlled files cannot be made trustworthy by signing it on the
  same machine. Submission now requires both
  `CODEX_STATS_LEADERBOARD_URL` and `CODEX_STATS_LEADERBOARD_KEY` for a private
  deployment. The public leaderboard needs server-side provider-issued usage
  attestations before verified submission can return.

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
