# 2026-01-27 Audio Capture Debugging

## Session Summary

See detailed handoff: `.aisteering/summaries/2026-01-27-audio-capture-debugging.md`

## TL;DR

- Fixed GStreamer audio capture for multiple recordings
- Key insight: always drain appsink, never block, one consumer only
- Remaining blocker: Alt+Space consumed by GNOME window manager
- Parakeet backend not registering (import issue?)

## Quick Resume

```bash
# Disable GNOME Alt+Space first
gsettings set org.gnome.desktop.wm.keybindings activate-window-menu "['']"

# Start engine
PYTHONPATH=src GSETTINGS_SCHEMA_DIR=data python3 -m speak2type --standalone &
ibus engine speak2type

# Check key events reaching engine
tail -f ~/.cache/speak2type/engine.log | grep "PTT check"
```

## Open Questions

1. ~~Why isn't Parakeet backend registering?~~ **RESOLVED** - Import errors were being swallowed. Now logged with `exc_info=True`.
2. Should we change hotkey from Alt+Space to something else?
3. Need to create/install GSettings schema

---

## 2026-01-27 Evening Session (Codex-assisted)

### Fixes Applied

**1. Backend import error logging** (`src/speak2type/backends/__init__.py`)
- Changed `LOG.debug()` to `LOG.warning(..., exc_info=True)` for all backend imports
- Now you'll see the actual exception (e.g., "No module named 'numpy'") in engine.log

**2. PTT release logic** (`src/speak2type/engine.py`)
- Added `_ptt_active` flag to track when PTT key is held
- On PTT press (Alt+Space): set flag and start recording
- On Space release: check flag instead of requiring modifier match
- This fixes the issue where Alt released before Space caused stop to not trigger
- Also reset `_ptt_active` on focus loss, disable, and reset events

### Root Causes Identified (via Codex/gpt-5.2)

1. **Parakeet "Unknown backend"**: Import fails silently because numpy/onnx_asr/onnxruntime aren't in IBus's Python interpreter
2. **Toggle behavior**: Release handler required same modifier mask as press; Alt released before Space = no stop

### To Test

```bash
# Start engine (use venv for numpy/onnx deps)
source .venv/bin/activate
PYTHONPATH=src GSETTINGS_SCHEMA_DIR=data python3 -m speak2type --standalone &
ibus engine speak2type
tail -f ~/.cache/speak2type/engine.log | grep -E "(PTT|Recording|Transcri)"
```

---

## 2026-01-27 ~15:36 - WORKING

### Additional Fix Applied

**3. GSettings null access** (`src/speak2type/engine.py:270`)
- `self._settings.get_string("locale")` crashed when schema not installed
- Fixed by adding null check before accessing settings

### Status: PTT Working
- Alt+Space triggers recording
- Release (even Alt-first) stops and transcribes
- Parakeet backend processing audio
- Text being committed to input fields

### Remaining Items
- Install GSettings schema for persistent settings

---

## 2026-01-27 ~20:00 - Switched to English-only model

**Issue**: v3 multilingual model was transcribing English as Russian ("Тест, тест, тест")

**Fix**: Changed `DEFAULT_MODEL` in `parakeet_adapter.py` from `nemo-parakeet-tdt-0.6b-v3` to `nemo-parakeet-tdt-0.6b-v2` (English-only)

**Status**: Working correctly with English transcription
