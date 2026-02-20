# Scratchpad: 2026-02-19 — Issue #7: Spaces on non-IBus interfaces

## Root cause analysis (updated after live log analysis)

### Actual bug mechanism (confirmed via fresh Cursor/Electron log)

The space flood is caused by a **race between IBus and the XDG Portal global shortcut**:

1. User holds **Ctrl+Space** → Both IBus `do_process_key_event` AND the XDG Portal `GlobalShortcuts` fire simultaneously.
2. IBus wins the race (arrives first) → starts recording, sets `_ptt_active=True`, `_ptt_source="ibus"`.
3. During recording, keyboard auto-repeat sends Ctrl+Space every ~30ms → all consumed by `return True`.
4. User releases Ctrl slightly **before** Space → keyboard auto-repeat continues but now sends **bare Space** (state=0, no Ctrl modifier).
5. Portal fires `Deactivated` signal → `_on_global_ptt_release()` sets `_ptt_active=False`, stops recording.
6. Bare Space events (keyval=32, state=0) hit `do_process_key_event`:
   - `_is_ptt_key()` fails (mods=0, want=4) → no PTT match
   - Release check fails (`_ptt_active=False`) → falls through
   - **`return False`** → Space leaks to app!

### Key insight from live testing

- **Chrome** (native Wayland) → Focus as `client=gnome-shell` → IBus works correctly, no leaks.
- **Cursor/Electron** (GTK3 IM via `gtk3-im:cursor`) → IBus key events DO arrive, but Portal deactivates before IBus key release, leaving absorb gap.
- **VS Code terminal / Claude Code** (`client=fake`) → IBus key events NOT delivered; portal path only; spaces leak from compositor directly.

The problem is NOT that Electron ignores `return True` — it's that the **Portal and IBus have different key release timing** for the same physical key.

## Fix 1: PTT key absorb mechanism

### `_absorb_ptt_key` flag
- Set to `True` when PTT starts (both IBus and global paths)
- In `do_process_key_event`: if flag is set and `keyval == _ptt_keyval`:
  - **press** → return True (consume, regardless of modifiers)
  - **release** → clear flag, stop recording if active, return True
- **Safety timeout** (1 second) via `GLib.timeout_add`: clears the flag if IBus key release is never seen
- Non-PTT keys pass through normally even when flag is set

### Critical bugfix: absorb guard must stop recording on release
The absorb guard initially ate the release event without stopping recording. This left the engine stuck in RECORDING state. Fixed by adding `_stop_recording()` call inside the absorb release handler.

## Fix 2: Anti-retrigger mechanism

### `_ptt_key_physically_released` flag
- Set to `False` when PTT starts (both IBus and global paths)
- Set to `True` on any PTT keyval release (absorb guard, regular PTT release, or post-timeout fallthrough)
- PTT activation via IBus **requires** this flag to be `True` — prevents auto-repeat events from starting a new recording session after the absorb timeout expires

### Why this is needed
Without this, after a 1s absorb timeout expires while the key is still held, the next auto-repeat event matches the PTT combo and starts an unwanted second recording session.

## Fix 3: Non-blocking clipboard copy

### `wl-copy` uses `Popen` (fire-and-forget)
- `wl-copy` is a foreground process by design (serves clipboard requests)
- Using `subprocess.run` with `timeout=5` caused 5-second blocking delays
- Changed to `subprocess.Popen` — process runs in background, engine continues immediately

## Fix 4: Time-based leaked space estimation

### `_ptt_start_time` for portal path
- When `_leaked_space_count == 0` (IBus didn't count any), estimate from recording duration
- Uses keyboard repeat rate (~33 repeats/sec) minus 500ms initial delay
- Provides reasonable cleanup even when IBus never sees the key events

## GNOME compatibility

### wtype does NOT work on GNOME Wayland
- Mutter doesn't support the `virtual-keyboard` Wayland protocol
- `ydotool` (uses `/dev/uinput`) is compositor-agnostic but requires daemon + permissions
- For now, unfocused apps get clipboard-only fallback
- Recommended workaround: **GNOME Settings → Accessibility → Typing**: Repeat Keys = Off, Sticky Keys = On

## Files changed
- `src/speak2type/engine.py`: `_absorb_ptt_key`, `_ptt_key_physically_released`, `_ptt_start_time`, non-blocking `_copy_to_clipboard`, time-based leak estimation, absorb guard stops recording on release
- `tests/test_unfocused_typing.py`: 11 tests in `TestAbsorbPttKey` including retrigger prevention
- `pyproject.toml`: Added `pythonpath = ["src"]` to pytest config
- `debian/control`: Removed wtype from Recommends
- `README.md`: Added GNOME Settings section (repeat keys off, sticky keys on), updated hotkey to Ctrl+Space

## Open questions
- `_leaked_space_count` is largely redundant now — absorb prevents most leaks. Keep for informational/edge-case purposes.
- The 1-second timeout is pragmatic. If user holds Space >1s after releasing modifier AND IBus release is lost, one space could slip through.
- GNOME upstream should fix GlobalShortcuts portal to suppress auto-repeats while grab is active (portal v1 merged Jan 2025).
