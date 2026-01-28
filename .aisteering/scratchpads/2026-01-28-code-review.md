# Scratchpad: 2026-01-28 Code Review

## Session Notes

- Ran unit tests: `24 passed, 3 skipped` via `.venv/bin/pytest -q`.
- Ran quality checks:
  - `ruff check src/speak2type` reports import-ordering and GI `require_version()`-related `E402` issues.
  - `ruff check .` is dominated by `src/upstream/` style violations (likely should be excluded).
  - `mypy src/speak2type` reports typing issues around optional backends/imports and GI types.
- Follow-up fixes applied (local working tree):
  - Lowered sensitivity of logs (key events + committed text) from `INFO` to `DEBUG`.
  - Removed machine-specific launcher `scripts/ibus-engine-speak2type` from git and added to `.gitignore`.
  - Removed broken benchmark entry point from `pyproject.toml` (use `python scripts/benchmark.py`).
  - Added a privacy note comment documenting why the audio pipeline stays `PLAYING`.

## Findings (high signal)

- `src/speak2type/backends/__init__.py:register_default_backends()` attempted to register `HttpBackend`, but the current block gates on `backend.is_available` which is false when `endpoint_url` is unset. Net effect: `http` still won’t be registered by default.
- `pyproject.toml` console script `speak2type-benchmark = "speak2type.scripts.benchmark:main"` points to a module that does not exist.
- Generated / environment-specific artifacts appear committed:
  - `src/speak2type/__pycache__/`
  - `speak2type.egg-info/` and `src/speak2type.egg-info/`
  - `scripts/ibus-engine-speak2type` contains an absolute path.
- Potential privacy risk: `AudioCapture.setup()` starts the GStreamer pipeline in `PLAYING` and leaves it running; may keep the microphone stream active even when not recording.
- Engine logs key events and committed text at `INFO` to `~/.cache/speak2type/engine.log` (potentially sensitive).
- Docs drift: `.aisteering/ARCHITECTURE.md` says “pipewiresrc preferred”, but `src/speak2type/audio_capture.py` prefers `pulsesrc`.

## Open Questions

1. Should “GSettings schema missing” be a hard error (fail fast) vs a supported fallback (requires policy exception)?
2. Is “mic stream always open while engine enabled” acceptable, or should capture only start on PTT press?
3. Should `src/upstream/` be excluded from lint/type-check (treat as vendored), or brought into compliance?

## Tasks

- None queued in this scratchpad (review only).
