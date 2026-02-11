# Scratchpad: 2026-02-11 Thorough Review

## Session Notes

- Scope reviewed: architecture boundaries, error handling, install flow, runtime security/privacy.
- Read project policy docs (`.aisteering/ARCHITECTURE.md`, `.aisteering/PRODUCT.md`,
  `.aisteering/TECHNOLOGY.md`, `.aisteering/policy-exceptions.md`) and core runtime code.
- Verified behavior with commands:
  - `pytest -q` -> `60 passed, 6 skipped`.
  - `.venv/bin/ruff check src tests` -> many issues (including vendored `src/upstream/`).
  - `.venv/bin/mypy src/speak2type` -> type errors in runtime modules.
  - `PYTHONPATH=src python3 -m speak2type.setup` -> module not found.
  - `PYTHONPATH=src python3 - <<'PY' ... HttpBackend.configure(...) ... PY` -> insecure HTTP endpoint accepted in `configure()`.

## Key Findings

- Sensitive dictated text is persisted in logs by default:
  - Debug logging forced in `engine.main()`.
  - Raw transcription text logged on commit/copy.
- Dev install script writes setup launcher to `python -m speak2type.setup`, but that module does not exist.
- Clipboard fallback for `xclip` passes `str` to `subprocess.run(..., input=...)` without text mode, which raises `TypeError`; clipboard copy fails on X11 path.
- HTTP backend validates endpoint security in constructor but not in `configure()` or `endpoint_url` setter.
- Model download security metadata is not pinned (`revision="main"`, empty `sha256`), and UI paths treat `None` download results as success.
- Engine enable/disable lifecycle is not symmetric:
  - `do_enable()` re-runs setup each time.
  - `do_disable()` does not teardown global hotkey, worker, or pipeline.
  - Risk of duplicate resources and capture remaining active after disable.
- Hotkey capture allows modifier-less keys (e.g. `space`) and engine accepts them, which can hijack regular typing.

## Coverage Gaps

- No direct tests for `engine.py`, `audio_capture.py`, `preferences.py`, or install scripts.
- No tests for clipboard fallback behavior or HTTP endpoint reconfiguration validation.

## Open Questions

1. Should global hotkey remain active when the engine is disabled, or only when selected?
2. Is logging of transcript content ever acceptable outside explicit debug opt-in?
3. Should runtime backend installs be restricted to signed/pinned artifacts only?
