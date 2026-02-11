# 2026-02-10: Bug Audit Fixes (High + Medium)

## What changed

9 issues fixed across 12 files. 65 tests pass (5 new).

### High priority
1. **Log level configurable** — Added `log-level` GSettings key (default: WARNING).
   ComboRow in preferences UI. Engine reads level at startup instead of hardcoded DEBUG.
   Transcribed text no longer logged to disk by default.
2. **Dev install launcher fixed** — `dev-install.sh:183` now references `speak2type.preferences`
   instead of nonexistent `speak2type.setup`.
3. **Clipboard X11 fix** — Added `text=True` to `subprocess.run()` in `_copy_to_clipboard()`
   to prevent `TypeError` when passing `str` input to xclip.
4. **Parakeet v2 model pinned** — `revision` set to commit `48b630d...`, sha256 computed
   and pinned. v3-multilingual remains `main` (gated model, needs HF token to pin).
5. **HTTP adapter validation** — Extracted `_validate_endpoint()` static method, called from
   constructor, `endpoint_url` setter, and `configure()`. Prevents downgrade to HTTP with auth.

### Medium priority
6. **Engine lifecycle symmetric** — `do_disable()` now tears down global_hotkey, worker, and
   audio_capture (matching `do_enable()` setup). Prevents stale resources across input-source switches.
7. **Model download failure detection** — `preferences.py` now checks `download_model()` return
   value; `None` triggers error toast instead of false success message.
8. **Modifier-less hotkeys rejected** — Hotkey capture requires at least one modifier
   (Ctrl/Alt/Shift/Super). Prevents binding bare keys like "space" as PTT.
9. **Backend errors not committed as text** — Added `error` field to `TranscriptResult`.
   Adapters set `error=...` + `text=""` on failure. Engine shows preedit error (3s timeout)
   instead of committing error strings to input or clipboard.

## Files modified
- `data/org.freedesktop.ibus.engine.stt.gschema.xml.in` — log-level key
- `src/speak2type/engine.py` — log level, clipboard fix, error handling, lifecycle
- `src/speak2type/preferences.py` — log level UI, download check, modifier validation
- `src/speak2type/types.py` — TranscriptResult.error field
- `src/speak2type/backends/parakeet_adapter.py` — error field
- `src/speak2type/backends/whisper_adapter.py` — error field
- `src/speak2type/backends/vosk_adapter.py` — error field
- `src/speak2type/backends/http_adapter.py` — error field + validation
- `src/speak2type/model_managers/parakeet.py` — pinned revision/sha256
- `scripts/dev-install.sh` — module reference fix
- `tests/test_backends.py` — updated error assertions + 5 new HTTP tests
- `tests/test_global_hotkey.py` — (from prior session, no changes this session)

## How to validate
```bash
PYTHONPATH=src python3 -m pytest tests/ -q  # 65 passed, 6 skipped
dpkg-buildpackage -us -uc -b && sudo dpkg -i ../speak2type_0.1.0-1_all.deb
ibus restart
# Preferences → General → Log Level dropdown visible
# Set hotkey to just "space" → toast rejection
# Check engine.log only has WARNING+ lines by default
```

## Notes
- v3-multilingual model still uses `revision="main"` — requires HF gated-access token to pin
- `do_disable()` now fully tears down resources; `do_enable()` re-creates them (safe per
  analysis of AudioCapture.setup, Worker.start, GlobalHotkeyListener.setup after teardown)
