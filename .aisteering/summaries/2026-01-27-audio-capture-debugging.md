# speak2type Audio Capture Debugging Summary

**Date**: 2026-01-27
**Session Duration**: ~3 hours
**Status**: Partially working, key issues remain

## What Was Being Built

speak2type is a speech-to-text IBus engine for GNOME/Linux. The goal was to implement push-to-talk (Alt+Space) recording that captures audio via GStreamer, sends it to a backend (Parakeet ONNX), and commits transcribed text.

## Issues Encountered & Fixes Applied

### 1. GStreamer Audio Capture Issues

**Problem**: Audio capture worked for first recording but failed on subsequent recordings.

**Root Cause**: Multiple GStreamer "footguns" (from external expert consultation):
- Blocking `try_pull_sample()` with timeout in `stop()` was breaking signal emission
- Not continuously draining appsink caused pipeline backpressure/stalls
- State changes (`PAUSED`, `READY`, `NULL`) all hang with pulsesrc

**Fix Applied** (`src/speak2type/audio_capture.py`):
```python
# Key insight: ALWAYS pull samples in callback, discard if not recording
def _on_new_sample(self, appsink):
    sample = appsink.emit("pull-sample")  # ALWAYS pull
    if sample is None:
        return Gst.FlowReturn.OK

    buf = sample.get_buffer()
    success, map_info = buf.map(Gst.MapFlags.READ)
    if not success:
        return Gst.FlowReturn.OK

    # Only buffer when recording, but always pull+unmap
    if self._is_recording:
        self._buffer.extend(map_info.data)

    buf.unmap(map_info)
    return Gst.FlowReturn.OK
```

**Appsink configuration**:
```python
self._appsink.set_property("emit-signals", True)
self._appsink.set_property("sync", False)
self._appsink.set_property("drop", True)  # Drop old buffers
self._appsink.set_property("max-buffers", 5)  # Small queue
```

**Critical rules learned**:
1. Only ONE consumer pulls from appsink (the signal callback)
2. Always pull samples to prevent backpressure, discard when not recording
3. Never do blocking state changes - keep pipeline in PLAYING
4. Removed polling mechanism (violated "one consumer" rule)

### 2. pipewiresrc Captures 0 Bytes

**Problem**: Native PipeWire source doesn't work.

**Fix**: Use `pulsesrc` instead (works via pipewire-pulse compatibility).

### 3. GSettings Schema Not Installed

**Problem**: `Gio.Settings.new()` causes fatal GLib error (abort) when schema missing.

**Fix**: Check schema existence before creating Settings object:
```python
schema_source = Gio.SettingsSchemaSource.get_default()
if schema_source and schema_source.lookup("org.freedesktop.ibus.engine.stt", True):
    self._settings = Gio.Settings.new("org.freedesktop.ibus.engine.stt")
else:
    self._settings = None  # Use defaults
```

Also fixed `_setup_backend()` which accessed `self._settings` without null check.

### 4. IBus Engine Activation

**Problem**: `ibus engine speak2type` fails with "connection closed" or "timeout".

**Partial Fix**:
- Engine works in standalone mode (registers own component)
- IBus mode (--ibus flag) doesn't work reliably
- Use standalone mode for now

## Current State

### Working
- Audio capture with multiple recordings (tested in isolation)
- GStreamer pipeline stays healthy after idle periods
- Engine starts and initializes
- IBus can activate engine (in standalone mode)
- Backend system (using placeholder - Parakeet not registered)

### NOT Working
- **Alt+Space hotkey not reaching engine** - Alt key is consumed by window manager/GNOME before IBus receives it. Key events show `state=0` (no modifiers) instead of `state=8` (Alt).
- **Parakeet backend not loading** - Shows "Unknown backend: parakeet" - backend registration issue
- **Toggle behavior** - When keys DO reach engine, it acts as toggle not push-to-talk

## Files Modified

| File | Changes |
|------|---------|
| `src/speak2type/audio_capture.py` | Major rewrite of sample handling, removed polling, fixed callback |
| `src/speak2type/engine.py` | GSettings null checks, debug logging for key events |
| `src/speak2type/__main__.py` | Created for module execution |

## Next Steps

### Immediate (to get working)

1. **Fix Alt+Space hotkey** - Either:
   - Use different key combo (Ctrl+Space, Super+Space)
   - Or configure GNOME to not capture Alt+Space
   - Check: `gsettings get org.gnome.desktop.wm.keybindings activate-window-menu`

2. **Register Parakeet backend** - Check why `register_default_backends()` isn't registering parakeet. Likely import error or missing dependency.

3. **Create GSettings schema** - Install schema to `~/.local/share/glib-2.0/schemas/` and compile.

### Commands to Test

```bash
# Start engine
PYTHONPATH=src GSETTINGS_SCHEMA_DIR=data python3 -m speak2type --standalone &

# Activate
ibus engine speak2type

# Check logs
tail -f ~/.cache/speak2type/engine.log

# Test audio capture in isolation
PYTHONPATH=src python3 -c "
from speak2type.audio_capture import AudioCapture
from gi.repository import GLib
import time

ac = AudioCapture()
ac.setup()
ctx = GLib.MainContext.default()

# Let pipeline start
for _ in range(100): ctx.iteration(False); time.sleep(0.01)

# Record
ac.start()
for _ in range(100): ctx.iteration(False); time.sleep(0.01)
seg = ac.stop()
print(f'Captured: {seg.duration_seconds:.2f}s' if seg else 'None')
"
```

### Disable GNOME Alt+Space (Window Menu)

```bash
gsettings set org.gnome.desktop.wm.keybindings activate-window-menu "['']"
```

## Reference: GStreamer Best Practices for Live Capture

From expert consultation:

1. **Keep pipeline PLAYING** - don't cycle states
2. **Always drain appsink** - callback must pull every sample
3. **Gate recording with flag** - not pipeline state
4. **One consumer only** - don't mix callback + polling + drain loops
5. **Small buffer + drop** - `max-buffers=5, drop=true`
6. **No blocking waits** - use timeouts, never `CLOCK_TIME_NONE`

Alternative pattern (more robust): Use `tee` with `fakesink` branch to keep pipeline healthy even if appsink stalls.

## Key Logs Location

- Engine log: `~/.cache/speak2type/engine.log`
- Look for: `PTT check`, `Started recording`, `KEY EVENT`
