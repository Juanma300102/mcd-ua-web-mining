## Why

A backfill runs for hours, and the run log of the Dagster UI only showed the start and end of each asset. Without progress lines there is no way to tell a slow sitemap or note from a stuck run.

## What Changes

- The catalog, raw and dataset assets log at INFO a start line, a progress line every `LOG_EVERY` (10) sitemaps or notes, and a summary with the same counts as their metadata. The code is in commit 657963b.
- An offline test reads the user log messages of a materialization and checks them.

Non-goals: no per-page logging inside the source clients, no debug logs, no metrics.

## Capabilities

### New Capabilities
<!-- None. -->

### Modified Capabilities
- `dagster-assets`: assets log their progress at INFO.

## Impact

- Changed: `src/news_politica/defs/assets.py` (already committed), `tests/defs/test_assets.py`.
- Network: none from tests.
