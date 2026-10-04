# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

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
