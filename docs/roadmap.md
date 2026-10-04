# Roadmap

`codex-stats` is one command that opens a local dashboard. The priority list below is
deliberately short: everything here has to earn its place against a single-command tool
that people run occasionally.

## Now

1. Dashboard polish
   Keep improving hierarchy, readability, spacing, and mobile behavior so the page feels
   obvious at a glance.
2. Export reliability
   Make PDF and JPG card exports reliable, predictable, and visually consistent across all
   time ranges.
3. Empty and edge states
   Handle sparse data, first-run usage, and low-history comparisons without awkward or
   confusing panels.

## Next

1. Session-level drilldown
   A project opens into its files; a session currently opens into nothing. The rollouts are
   already parsed line by line, so the tools, files, and branch behind one session are
   available and only the view is missing.
2. Spend thresholds
   The dashboard can say usage moved up 74% and that a month projects to $145, but nothing
   is compared against a number the user chose. A monthly budget belongs in the existing
   `config.toml`, which keeps it out of the CLI surface ruled out below.
3. Cache efficiency as a trend
   Cache reuse is reported as a single ratio per window. The interesting question is how it
   moves over time and whether long sessions are paying for cache they never hit.
4. Source metadata
   OpenCode records neither a branch nor a model family, and Hermes leaves both null for
   sessions started outside a checkout, so that spend lands in the unattributed bucket. Both
   would benefit from parsing whatever those databases do keep.

## Done

1. Spend joined to the work it bought
   An Efficiency panel that divides a window's spend by the file edits recorded in the same
   sessions: cost per 1k lines, per file, and per editing session, the share of spend on
   sessions that changed nothing, a rework ratio, and the most-rewritten files across every
   project. On the Overview, a per-tool version answers which agent is worth its cost.
   Scoped to the sources that actually record edits, so an unmeasurable tool is labelled
   rather than ranked.
2. Bounded history across all four sources
   OpenCode and Hermes read their entire history on every launch while the README claimed
   all four were capped. Every source now honors `CODEX_STATS_MAX_SESSIONS`, and the
   coverage note names each source it truncated instead of reporting one blended Codex
   total that could not describe the other three.
3. One unreadable source no longer takes down the dashboard
   A schema change in any tool's database raised out of ingest and killed the other three
   tabs. Each source now degrades to its empty state, and an unrecognized file-edit action
   is counted instead of raising.
4. Coverage for `display.py`
   `tests/test_display.py` now pins the panels the renderer emits, including a markup
   balance check that catches an unbalanced tag, which a browser would otherwise render
   silently.
5. Branch-level spend
   Spend broken down per repository *and* branch, with branches that went quiet totalled
   separately as paid-for work that never finished.

## Explicitly Out of Scope

These were built and then removed as unreached surface area. Do not reintroduce them
without a concrete use case:

- JSON export, import, and multi-machine merge
- CLI flags for output path, headless mode, or source filtering

## Known Limits

- Tool-call and message tables are read whole and filtered in Python, because neither
  OpenCode nor Hermes records tool calls in a shape that can be filtered in SQL by session
  id. The session cap therefore bounds session rows but not the tool-call read behind them,
  so startup on a very long history is still slower than the session count alone suggests.
