# 2026-02-19: Fix #7 — Spaces on non-IBus interfaces

## What changed

**Root cause**: When holding Ctrl+Space for PTT, both IBus and the XDG Portal GlobalShortcuts fire. The Portal sends `Deactivated` before IBus sees the key release. After that, if Ctrl is released before Space, auto-repeat sends bare Space events that bypass PTT checks — flooding the app with spaces.

### Fixes applied

1. **PTT key absorb mechanism** (`_absorb_ptt_key` flag) — consumes all PTT keyval events (press/release, any modifier state) while PTT is active. Clears on physical key release or 1s safety timeout. **Crucially**, the absorb guard now also stops recording on release (was missing, caused engine to stay stuck in RECORDING).

2. **Anti-retrigger** (`_ptt_key_physically_released` flag) — prevents auto-repeat events from starting a new recording session after the absorb timeout expires. Requires seeing a physical key release before re-activation.

3. **Non-blocking clipboard** — `wl-copy` now uses `Popen` (fire-and-forget) instead of `subprocess.run` with 5s timeout that was blocking the engine.

4. **Time-based leaked space estimation** — when IBus didn't count leaked spaces (portal-only path), estimates from recording duration using keyboard repeat rate.

5. **README: GNOME settings** — added section recommending Repeat Keys = Off, Sticky Keys = On for best PTT experience. Updated hotkey from Alt+Space to Ctrl+Space.

### Files modified
- `src/speak2type/engine.py` — absorb guard, anti-retrigger, non-blocking clipboard, time-based estimation
- `tests/test_unfocused_typing.py` — 11 new tests in `TestAbsorbPttKey` class
- `pyproject.toml` — `pythonpath = ["src"]` for pytest
- `debian/control` — removed wtype from Recommends
- `README.md` — GNOME settings section, hotkey update

## How to validate
```bash
python3 -m pytest tests/ -q  # 95 passed, 6 skipped
# End-to-end:
# 1. Install .deb, restart IBus, set engine to speak2type
# 2. GNOME Settings → Accessibility → Typing: Repeat Keys = Off, Sticky Keys = On
# 3. Focus Cursor / VS Code / Chrome
# 4. Hold Ctrl+Space to record, release → verify no space flood
# Check ~/.cache/speak2type/engine.log for "PTT released via absorb guard" lines
```

## Risks
- 1s absorb timeout is pragmatic; edge case if IBus release lost and key held >1s
- Unfocused apps (client=fake) get clipboard-only fallback (no auto-paste on GNOME Wayland — wtype unsupported, ydotool needs daemon)
- GNOME GlobalShortcuts portal (v1, merged Jan 2025) has rough edges with key repeat during grabs — should be fixed upstream

## Next steps
- End-to-end verification with GNOME accessibility settings applied
- Close issue #7 after verification
- Consider simplifying `_leaked_space_count` (mostly redundant with absorb)
- Consider filing upstream GNOME bug for portal key repeat suppression
