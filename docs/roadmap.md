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

1. Cache efficiency as a trend
   Cache reuse is reported as a single ratio per window. The interesting question is how it
   moves over time and whether long sessions are paying for cache they never hit.
2. Hermes per-model usage
   Hermes keeps a `session_model_usage` table the dashboard does not read; when it
   populates, the model column could carry totals instead of the logged model alone.

## Done

1. Spend joined to the work it bought
   An Efficiency panel that divides a window's spend by the file edits recorded in the same
   sessions: cost per 1k lines, per file, and per editing session, the share of spend on
   sessions that changed nothing, a rework ratio, and the most-rewritten files across every
   project. On the Overview, a per-tool version answers which agent is worth its cost.
   Scoped to the sources that actually record edits, so an unmeasurable tool is labelled
   rather than ranked.
2. Session-level drilldown
   A project opens into its files; a session now opens into its tools, file edits, token
   split, and branch. Clicking a top session expands it in place instead of opening nothing.
3. Spend thresholds
   A monthly budget in `config.toml` (`[budget]`). The Overview names the sources and
   months it can price, warns when this calendar month reaches a chosen share of the limit,
   and says outright when pricing is missing so a silence is not read as health.
4. Bounded history across all four sources
   OpenCode and Hermes read their entire history on every launch while the README claimed
   all four were capped. Every source now honors `CODEX_STATS_MAX_SESSIONS`, and the
   coverage note names each source it truncated instead of reporting one blended Codex
   total that could not describe the other three.
5. One unreadable source no longer takes down the dashboard
   A schema change in any tool's database raised out of ingest and killed the other three
   tabs. Each source now degrades to its empty state, and an unrecognized file-edit action
   is counted instead of raising.
6. Coverage for `display.py`
   `tests/test_display.py` now pins the panels the renderer emits, including a markup
   balance check that catches an unbalanced tag, which a browser would otherwise render
   silently.
7. Branch-level spend
   Spend broken down per repository *and* branch, with branches that went quiet totalled
   separately as paid-for work that never finished.
8. Source metadata
   OpenCode records a branch and a model family for most sessions but the dashboard only
   read the cost and token columns. Sessions now carry the recorded file-change totals,
   and the drilldown surfaces a Hermes compression counter that records context rewrites
   that did not shrink a session. Anything those databases do not record stays
   "Not recorded" rather than reading as zero.
9. Project identity
   Projects are keyed by working directory, so two checkouts with the same folder name no
   longer merge. Labels disambiguate with `parent/name` or the full path, and the filter
   accepts any displayed form.
10. Ingest cache
    Parsed sessions are cached per source and reused until the source fingerprint or
    session cap changes, keeping repeat launches fast without changing first-run accuracy.
11. Source health and search
    The dashboard lists each source's path, session count, notes, and ingest failure, and
    the action bar filters sessions, projects, and models.
12. Budget and trend correctness
    The budget uses calendar-month spend instead of rolling 30 days, per-project limits can
    stand alone, runway uses a seven-day burn rate, and efficiency trends render real
    weekly or monthly buckets.
13. Export and embedding safety
    Dashboard JSON escapes `<`, `>`, `&`, and line separators before entering a script
    block, and opening the report falls back with a clear message when no browser is available.
14. Opt-in leaderboard and CI gates
    Leaderboard submission is off unless explicitly enabled. CI now runs lint, type checks,
    tests, and branch coverage on Python 3.11 through 3.14.

## Explicitly Out of Scope

These were built and then removed as unreached surface area. Do not reintroduce them
without a concrete use case:

- JSON export, import, and multi-machine merge
- CLI flags for output path, headless mode, or source filtering

## Known Limits

- Tool calls and request counts are now filtered in SQL by session id for both OpenCode
  and Hermes, so the read stays bounded by the session cap. A malformed JSON blob falls
  back to a per-session parse in Python, but that parse is still scoped to the sessions
  being read.
- OpenCode records `summary_*` columns the dashboard can surface, but this install has
  never populated them, so the drilldown shows an honest "no per-session readout".
- Hermes populates `compression_ineffective_count` in the dashboard only when the source
  has recorded one; the local install has none, so the insight that counts them is
  normally silent.
