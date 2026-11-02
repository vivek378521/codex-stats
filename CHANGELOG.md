# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [1.20.0] - 2026-11-02

### Added

- **Context Tax flow diagram.** The waste ledger now visualizes total spend
  flowing into useful work or waste, then splitting waste across context,
  re-read, and failure taxes. Ribbons scale with estimated dollars, legend
  cards show counts, tokens, and shares, and hover titles expose each amount.

## [1.19.0] - 2026-11-01

### Added

- **Session outcomes and verification.** A new Outcomes panel classifies
  sessions as PR created, verified, completed, unresolved errors, or
  interrupted, and reports how often an edit was followed by a successful
  test, lint, typecheck, or build. Outcome counts and the verification rate
  render as a bar chart plus KPIs.
- **Context hygiene.** A new panel reports compaction count and rate, peak
  context tokens, average context before and after compaction, and files
  re-read after a compaction that had been read before it. Codex, Claude Code,
  and DeepSeek Harness now capture their compaction boundaries; Codex and
  Claude Code also capture peak context occupancy.
- **MCP, skill, and subagent breakdown.** Tool behavior now attributes calls to
  MCP servers (`mcp__<server>__<tool>`), skill names, and subagent types, with
  per-capability calls, failures, and session counts.
- **Waste ledger.** A new estimated-dollar ledger splits spend across retries,
  abandoned sessions, cold-context premium, duplicate reads, and failed
  subagents. Every row explains what it measures, and the panel states that
  tool-level figures are allocated evenly because sources bill per session.
- **Structured source metadata.** Tool calls now record command verbs,
  verification and PR-create detection, MCP server, skill, subagent type, and
  file path from both structured arguments and shell commands.

### Changed

- **Ingest cache format.** The cache version is bumped so cached sessions from
  older releases are re-read with the new tool and compaction fields.

## [1.18.0] - 2026-10-26

### Added

- **Project grouping by working directory.** Sessions are no longer merged just
  because two checkouts share a folder name; metrics, branch tables, history,
  spotlights, drilldowns, and project filtering now use the full project path.
  Display labels fall back from `name` to `parent/name` to a full path only when
  needed, and the project filter accepts the same labels.
- **Source health panel and search.** The dashboard now lists every source's
  path, session count, decoder note, and ingest error under **Data sources**,
  and the action bar has a filter for sessions, projects, and models.
- **Real efficiency trends.** The Efficiency Trend panel now buckets weekly (up
  to 60 days) or monthly and reports cost per 1k lines, read/write ratio,
  read-only share, and cache ratio for each bucket instead of rendering an empty
  table.
- **Per-project budgets.** `[budget.projects]` limits compare each project's
  calendar-month spend against its own limit and name the project in the warning.
- **Ingest cache.** Parsed sessions are cached per source under the dashboard
  cache directory and reused while the source fingerprint and
  `CODEX_STATS_MAX_SESSIONS` are unchanged.
- **dsh decoder diagnostics.** When compressed dsh sessions exist but the
  decoder is unavailable, the source note explains how to install `zstandard`
  instead of silently reporting no sessions.
- **CI quality gates.** Python 3.11–3.14 now run ruff, mypy, tests, and coverage
  (`fail_under = 85`, branch coverage enabled).

### Changed

- **Leaderboard is opt-in.** Set `CODEX_STATS_ENABLE_LEADERBOARD=1` to enable
  the embed, local submit endpoint, and button. `CODEX_STATS_DISABLE_LEADERBOARD`
  still wins when both are set.
- **Runway uses the calendar month and recent daily burn.** Budget runway now
  compares the configured monthly limit against calendar-month spend (falling
  back to rolling-month spend), ignores future/out-of-window points, and uses the
  last seven days for burn rate.
- **Existing SQLite sources are opened read-only.** The dashboard no longer
  writes journals or creates files next to a source database; missing databases
  still fall back to read-write creation for test isolation.
- **Hermes queries are chunked by session id.** Message reads use
  `WHERE session_id IN (...)` in batches of 500 instead of scanning the table.
- **Coverage notes include source notes and ingest errors.** One unreadable
  source degrades to an empty tab with its error shown, while other sources keep
  their data.

### Fixed

- Cost summaries now carry a distinct calendar-month figure; the budget banner
  no longer compares a rolling 30-day figure against a monthly limit.
- Efficiency trend no longer returns empty points while claiming support.
- Regression snapshots use the monthly window, skip empty snapshots, and compare
  only within the same window key.
- Dashboard JSON is escaped for `<`, `>`, `&`, U+2028, and U+2029 before being
  embedded in a script, so model or path text cannot close the script block.
- `tool_daily_points` no longer crashes while serializing a window.
- Project and branch labels, top sessions, history, spotlights, and session
  drilldowns remain consistent when projects share a basename.
- Ruff and mypy issues across `src` were resolved, including missing
  annotations, import order, and unused imports.
- Removed a duplicated sentence in the README's vendor note.

## [1.17.0] - 2026-10-20

### Added

- **DeepSeek Harness source.** The dashboard now reads dsh sessions from
  `$DSH_HOME/sessions` (override with `CODEX_STATS_DSH_HOME`), parsing the
  per-session JSONL event logs that dsh writes — including the zstd-compressed
  generations it has written by default since v2. Requests are counted from
  genuine user messages, token usage is summed across assistant turns and
  compaction summaries into the four normalised buckets (dsh reports
  cache writes separately, though DeepSeek bills none), tool calls are paired
  with their results for status and duration, and `edit`/`write` tool calls
  reconstruct per-file insertions and deletions, so DeepSeek Harness joins
  Codex and Claude Code in the efficiency and file-impact panels. Sessions
  written by a newer, unknown format version are skipped rather than
  mis-parsed, and a torn zstd tail (the crash signature of an interrupted
  writer) keeps the complete frames instead of losing the session.
- **DeepSeek pricing.** Off-peak published rates for the `deepseek-flash` and
  `deepseek-v4-pro` tiers (plus the retired `deepseek-chat`/`deepseek-reasoner`
  aliases still found in historical sessions). Peak-hour double rates are not
  modelled and the snapshot says so.
- **dsh tool taxonomy.** dsh's `terminal_*`/`job_*` tools classify as Execute,
  `send_message`/agent tools as Subagent, and goal/plan tools as Plan, so the
  Tool Behavior panel covers the new source without inventing categories.

## [1.15.0] - 2026-10-07

### Added

- **Session drilldown.** Top sessions are now a list you can click. Each row
  expands in place to show the session's branch, provider, created and last
  updated times, request count, token split (fresh input / cache reads / cache
  writes / output), the tools it called, and the files it edited. Panels render
  only what the source records: Hermes sessions with a compression
  ineffective-rewrite counter show it, and OpenCode file-change totals appear
  when its `summary_*` columns are populated. Tools that record none of it are
  labelled "Not recorded" rather than presented as zero.
- **Insights that keep their integrity.** Insights now notice when a context
  rewrite "bought" no space. The count comes only from what a source actually
  records (`compression_ineffective_count`), so a tool that has never recorded
  one stays silent instead of being reported as healthy.
- **Monthly spend thresholds.** A `[budget]` table in `config.toml` with a
  `monthly_limit_usd` and an optional `warn_at_ratio` (default 0.8). When the
  current calendar month's spend reaches that ratio of the limit, the dashboard
  says so with a note under the totals; going over the limit changes the note to
  an over-budget warning. The note names the sources and months it can price,
  and says outright when pricing is missing, rather than reading a silent
  comparison as a healthy one.
- **Leaderboard.** The README now documents the optional leaderboard
  submission: what is sent, what is never sent (rollout paths, prompts, tool
  calls, token counts), the device id's message-authentication, and the meaning
  of the shared key baked into the wheel.

### Changed

- **Startup reads are now scoped in SQL, not brewed in Python.** OpenCode
  request counts and tool calls were read whole and filtered in Python; a long
  history cost real time even after the session cap. Both are now `WHERE
  session_id IN (...)` reads with chunked parameters, and the malformed-JSON
  fallback is scoped to the sessions being read. An isolated warm ingest of the
  local OpenCode history went from seconds that scaled with history length to
  ~0.4s.
- **The single-file dashboard got roughly a megabyte lighter.** The embedded
  chart assets were base64 of full SVGs; they are now gzip-compressed first
  (~1.4 MB to ~206 KB of payload) and only the requested card is inflated when
  exported. Total page weight dropped from ~3.9 MB to ~2.9 MB with no change in
  the exports.
- **The coverage note reuses work already done.** `_coverage_note` now takes
  the already-built source objects instead of re-walking the source databases a
  second time on every build.

## [1.16.0] - 2026-10-12

### Added

- **Regression detection vs last run.** On each run, a small snapshot of key metrics is saved to the cache; next run computes deltas (cost/1k lines, repeat rate, read-only share) and prints/ displays a short "vs last run" diff.
- **Top leaks view.** Surfaces concrete offenders (repeated tool calls/time, tool failures, most expensive idle branches, most-rewritten files) as banner bullets and per-window "Leaks" panels.
- **Runway & burn rate.** Projects days until hitting the configured `[budget]` limit using recent burn rate, with on-track/approaching/exceeding status; also accepts per-project limits in `[budget.projects.*]`.
- **Efficiency trends.** Adds an "Efficiency Trend" panel per window (cost/1k lines, read/write ratio, read-only share where available).
- **Offender-aware takeaways.** Takeaways now include the specific worst offender when present (measured facts outrank generic advice).

## [1.14.0] - 2026-10-04

### Added

- Every control on the dashboard now shows a **visible focus ring** under
  keyboard navigation. The scope tabs, range tabs, export menu, and project tabs
  were previously reachable by keyboard with nothing marking where focus was, so
  the page's primary navigation could only be operated by pointing at it.
- Honoured `prefers-reduced-motion`. The hover lift on buttons was the only
  motion in the interface, and it is now removed outright for readers who ask
  for reduced motion rather than merely shortened, because a hover that jumps
  instead of transitioning reads as a glitch.
- The selected tab is now marked by a shape as well as a colour: an inset ring
  sits inside the active scope, range, and project tabs. Fill colour alone left
  the selected tab indistinguishable in forced-colors mode, and ambiguous for a
  reader who cannot separate the teal fill from the cream page.

### Changed

- **Figures are set in a lining sans with tabular spacing; headings keep the
  serif.** Cost, token, and percentage tables were previously set in Georgia,
  whose proportional figures do not align down a column, so reading a ranking
  meant reading each figure rather than scanning the column. Tabular spacing
  makes every digit the same width, so a cost ranking can be scanned at a glance.
  Headings and prose keep the serif that gives the page its voice.
- Declared `color-scheme: light`, so scrollbars and form controls match the page
  instead of following the operating system's appearance.

## [1.13.0] - 2026-10-04

### Added

- **Efficiency** panel: spend joined to the file edits recorded in the same
  sessions. Reports cost per 1k lines changed, cost per file, cost per editing
  session, the share of spend that went to sessions which changed no files, a
  rework ratio (deletions over insertions), and how many files the window left
  smaller than it found them. Every other panel answers "how much" or "where";
  this one answers "for what".
- Per-tool efficiency on the Overview, ranking each tool's spend against the
  lines it actually changed. This is the comparison a multi-agent user cannot
  make anywhere else: which of the installed agents is worth its cost.
- **Most Rewritten Files** table, ranked by how many separate sessions touched a
  file and spanning every project at once. File impact was previously only
  visible from inside one project's drilldown, so a file that was hard in three
  different repositories could never appear as one problem.
- Efficiency findings are now takeaways, interleaved with the tool-behavior and
  branch facts. They are measured rather than heuristic, so they rank ahead of
  the cost advice in the same way those facts already did.

### Fixed

- OpenCode and Hermes read their **entire** history on every launch while the
  README stated all four sources read only the 2,000 most recent sessions. Both
  now honor `CODEX_STATS_MAX_SESSIONS`, which is what made startup predictable
  on long histories in the first place.
- The coverage note reported only Codex, so a truncated OpenCode or Hermes
  history was presented as a complete one. It now names each source it truncated
  and how much of that source it kept.
- The OpenCode source description named `opencode.sqlite`; the file it opens is
  `opencode.db`.
- A schema change in any one tool's database raised out of ingest and took the
  other three tabs down with it. Each source now degrades to its empty state, so
  a drifted schema costs one tab instead of the dashboard.
- An unrecognized file-edit action raised `KeyError` from the unconditional
  file-impact build and took down the whole dashboard. Unknown actions are now
  counted and appear in none of the created/updated/deleted columns, which is
  visibly a lower total rather than a crash.
- Tests that built a dashboard isolated only Codex, so they silently merged
  whatever the developer had installed locally for the other three tools. Every
  such test now pins all four sources, which is what made the coverage-note bug
  visible in the first place.

## [1.12.0] - 2026-10-02

### Added

- Branch-level spend: a **Branches** panel in every window that ranks work by cost
  per branch rather than per repository, so five branches of one project no longer
  collapse into a single number. Sessions are grouped per repository *and* branch,
  because a branch name is only unique inside its own checkout.
- Branches that went quiet are totalled separately and marked in the table. A
  branch that consumed tokens and then stopped is paid-for work that never
  finished, which no project-level view can show. Idle spend is now also a
  takeaway, where it outranks the heuristic cost advice.
- Branch data now also comes from Claude Code transcripts, which record a
  `gitBranch` per event alongside Codex's session database. OpenCode records
  no branch, and Hermes leaves it null outside a checkout, so sessions without
  one never appear in the panel, and the empty state says so rather than
  implying no work happened.
- Provider breakdown: a **Providers** panel attributing spend to the billing
  vendor. Vendors are resolved from the model name with any `vendor/` prefix
  stripped, not from the recorded provider, because Codex records the real vendor
  while OpenCode and Hermes record their own CLI name there and may route to any
  vendor underneath.
- Reasoning-token share in Work Patterns. Reasoning tokens were already summed
  and priced but never displayed, so on a reasoning model a meaningful share of the
  bill was invisible. Tools that do not report the figure show "Not reported"
  rather than a misleading 0%.
- `tests/test_display.py`, covering the renderer for the first time. It pins the
  panels the page emits and includes a markup balance check, which catches an
  unclosed tag that a browser would otherwise render silently.
- `XDG_CACHE_HOME` now controls where the dashboard is written.

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

- The dashboard is written to a fixed `~/.cache/codex-stats/dashboard.html`
  instead of a new temporary file on every run. The page is something people come
  back to, so it has to be reopenable and refreshable in place; a new random
  filename each launch made yesterday's bookmark show stale numbers with no way to
  tell, and left an orphan in the temp directory every time.
- Opening the dashboard now appends the file's mtime to the URL. With a stable
  path, a plain `file://` open could be served from the browser cache and show
  the previous run's numbers; the timestamp makes a changed file a changed URL
  while leaving an unchanged file on the tab that is already open.
- A Claude Code session that switched branches mid-run is attributed to the branch
  most of its events landed on, mirroring how a session's model is already chosen,
  instead of whichever branch happened to be last.

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

### Fixed

- A detached checkout no longer appears as a branch named `HEAD`. It is reported as
  having no branch, because ranking it would invent a workstream out of whatever
  commit happened to be checked out.
- Two test fixtures leaked open SQLite connections, which surfaced as
  `ResourceWarning: unclosed database` during unrelated later tests. The suite now
  runs clean under `-W error::ResourceWarning`.

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
