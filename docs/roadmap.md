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

1. More source metadata
   Branch data comes from Codex, Claude Code, and Hermes. OpenCode records neither a branch
   nor a model family, and Hermes leaves both null for sessions started outside a checkout,
   so that spend lands in the unattributed bucket. Both would benefit from parsing whatever
   those databases do keep.
2. Cache efficiency as a trend
   Cache reuse is reported as a single ratio per window. The interesting question is how it
   moves over time and whether long sessions are paying for cache they never hit.
3. Source parsing resilience
   Local file formats drift. Isolate per-source parse failures so one broken transcript
   or schema change cannot take down the whole dashboard.

## Done

1. Coverage for `display.py`
   `tests/test_display.py` now pins the panels the renderer emits, including a markup
   balance check that catches an unbalanced tag, which a browser would otherwise render
   silently.
2. Branch-level spend
   Spend broken down per repository *and* branch, with branches that went quiet totalled
   separately as paid-for work that never finished.

## Explicitly Out of Scope

These were built and then removed as unreached surface area. Do not reintroduce them
without a concrete use case:

- JSON export, import, and multi-machine merge
- CLI flags for output path, headless mode, or source filtering
