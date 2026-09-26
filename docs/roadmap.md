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

1. Coverage for `display.py`
   The HTML renderer is the largest module in the project and the least tested. Add
   assertions for the panels it emits before changing its markup.
2. Source parsing resilience
   Local file formats drift. Isolate per-source parse failures so one broken transcript
   or schema change cannot take down the whole dashboard.

## Explicitly Out of Scope

These were built and then removed as unreached surface area. Do not reintroduce them
without a concrete use case:

- JSON export, import, and multi-machine merge
- CLI flags for output path, headless mode, or source filtering
