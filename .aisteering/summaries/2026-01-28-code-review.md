# Repo Code Review Summary

**Date**: 2026-01-28
**Scope**: Repo-wide review (Python package, scripts, server, and tooling)

## What changed
- Added scratchpad notes: `.aisteering/scratchpads/2026-01-28-code-review.md`.
- Recorded this session summary.
- Verified follow-up fixes on the working tree and re-ran tests (`24 passed, 3 skipped`).

## Why
- User requested a code review of the repository.

## How to validate
- Unit tests: `.venv/bin/pytest -q`
- Lint (currently fails): `.venv/bin/ruff check src/speak2type`
- Type check (currently fails): `.venv/bin/mypy src/speak2type`

## Notes / risks
- HTTP backend registration is still effectively off by default because it’s gated on `HttpBackend.is_available` (false until `endpoint_url` is set).
- Potential privacy issue if the mic stream is kept active while the engine is enabled (pipeline stays `PLAYING`).
- Tooling drift: `ruff`/`mypy` aren’t currently green, and `src/upstream/` dominates lint output unless excluded.
- Generated artifacts (egg-info, pyc, absolute-path launcher) appear committed; one launcher was removed from git and added to `.gitignore`.

## Next steps
- Decide on the privacy posture (mic stream lifecycle) and settings-schema behavior (required vs fallback).
- Decide how HTTP backend should be configured (GSettings vs env vars) and register it accordingly.
- Tighten lint/type-check configuration (exclude vendored `src/upstream/` or bring it into compliance).
