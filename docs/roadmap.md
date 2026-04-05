# Roadmap

This is the prioritized path to make `codex-stats` more operational, more visual, and easier to adopt.

## Now

1. Grafana starter kit
   Added in `examples/grafana/` so OTLP export is immediately usable with a dashboard and collector config.
2. Better OTLP documentation
   Make setup and expected metric names obvious.
3. `watch` mode
   Added as a live terminal dashboard for rolling summaries, trends, and recent sessions.

## Next

1. Budget alerts
   Add config thresholds for cost, tokens, and request spikes.
2. Project grouping
   Allow aliases like `frontend`, `backend`, or `client-work` to combine multiple repos.
3. Better watch triggers
   Highlight new sessions, request spikes, and unusually expensive refreshes with stateful change detection.

## Later

1. Terminal dashboard
   A TUI with live panes for totals, trends, projects, and sessions.
2. Session timeline
   Visualize token growth and request cadence inside a session.
3. What-if cost simulator
   Re-price historical usage under different models or rates.

## Nice To Have

1. Team rollups
   Merge exports from multiple machines into org-level reports.
2. Shareable digests
   Generate polished weekly reports for Slack, email, or PR comments.
3. Efficiency scoring
   Rank projects or sessions by tokens per request, cache ratio, and session sprawl.
