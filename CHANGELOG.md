# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[semantic versioning](https://semver.org/spec/v2.0.0.html).

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
