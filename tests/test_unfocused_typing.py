"""Tests for unfocused text typing (issue #7 — space leak on non-IBus apps).

Covers:
- PTT key absorb mechanism (prevents bare-key flooding after modifier release)
- Leaked space counting during PTT key repeat
- Cleanup + paste via wtype (Wayland) and xdotool (X11)
- Fallback to clipboard-only when tools are unavailable
"""

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

import gi

gi.require_version("IBus", "1.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")

from gi.repository import IBus, GLib

from speak2type.engine import (
    Speak2TypeEngine,
    DEFAULT_PTT_KEYVAL,
    DEFAULT_PTT_MODIFIERS,
)
from speak2type.types import EngineState, TranscriptResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> Speak2TypeEngine:
    """Create a minimally-initialized Speak2TypeEngine for testing.

    Patches out IBus.Bus, GSettings, AudioCapture, GlobalHotkeyListener,
    and backend registration so the engine can be instantiated without
    a running IBus daemon.
    """
    mock_bus = MagicMock(spec=IBus.Bus)
    mock_bus.get_connection.return_value = MagicMock()

    with (
        patch("speak2type.engine.Gio.SettingsSchemaSource.get_default", return_value=None),
        patch("speak2type.engine.AudioCapture"),
        patch("speak2type.engine.GlobalHotkeyListener"),
        patch("speak2type.engine.register_default_backends"),
        patch("speak2type.engine.get_registry") as mock_registry,
        patch.object(IBus.Engine, "__init__", lambda *a, **kw: None),
        patch.object(IBus.Engine, "update_property"),
        patch.object(IBus.Engine, "register_properties"),
    ):
        mock_registry.return_value.set_current.return_value = False
        mock_registry.return_value.available_backends = []
        engine = Speak2TypeEngine(mock_bus, "/test/path")

    return engine


# ---------------------------------------------------------------------------
# PTT key absorb mechanism (prevents bare-space flooding)
# ---------------------------------------------------------------------------


class TestAbsorbPttKey:
    """After PTT, bare key presses (without modifier) must be consumed."""

    def test_absorb_set_on_ibus_ptt_start(self):
        """Starting PTT via IBus sets _absorb_ptt_key."""
        engine = _make_engine()
        engine._state = EngineState.IDLE
        engine._recording_disabled = False
        engine._audio_capture = MagicMock()
        engine._audio_capture.is_setup = True
        engine._audio_capture.start.return_value = True

        with patch.object(engine, "update_preedit_text"), patch.object(
            engine, "update_property"
        ):
            engine.do_process_key_event(
                DEFAULT_PTT_KEYVAL, 0, int(DEFAULT_PTT_MODIFIERS)
            )

        assert engine._absorb_ptt_key is True

    def test_absorb_set_on_global_ptt_start(self):
        """Starting PTT via portal sets _absorb_ptt_key."""
        engine = _make_engine()
        engine._state = EngineState.IDLE
        engine._recording_disabled = False
        engine._audio_capture = MagicMock()
        engine._audio_capture.is_setup = True
        engine._audio_capture.start.return_value = True

        with patch.object(engine, "update_preedit_text"), patch.object(
            engine, "update_property"
        ):
            engine._on_global_ptt_press()

        assert engine._absorb_ptt_key is True

    def test_bare_space_consumed_during_transcribing(self):
        """Bare Space (no modifier) is consumed when absorb flag is set."""
        engine = _make_engine()
        engine._state = EngineState.TRANSCRIBING
        engine._absorb_ptt_key = True

        # Bare space press — no modifier
        result = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, 0)

        assert result is True, "Bare space should be consumed"
        assert engine._absorb_ptt_key is True, "Flag stays set until release"

    def test_bare_space_consumed_during_idle(self):
        """Bare Space consumed even after returning to IDLE (auto-repeat tail)."""
        engine = _make_engine()
        engine._state = EngineState.IDLE
        engine._absorb_ptt_key = True

        result = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, 0)

        assert result is True

    def test_absorb_cleared_on_key_release(self):
        """Physical key release clears the absorb flag."""
        engine = _make_engine()
        engine._absorb_ptt_key = True

        release_state = int(IBus.ModifierType.RELEASE_MASK)
        result = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, release_state)

        assert result is True, "Release event itself should be consumed"
        assert engine._absorb_ptt_key is False, "Flag must be cleared"

    def test_absorb_does_not_eat_other_keys(self):
        """Non-PTT keys pass through even when absorb is set."""
        engine = _make_engine()
        engine._absorb_ptt_key = True

        result = engine.do_process_key_event(IBus.KEY_a, 30, 0)

        assert result is False

    def test_absorb_cleared_on_ibus_release(self):
        """Normal IBus PTT release clears absorb flag and stops recording."""
        engine = _make_engine()
        engine._state = EngineState.RECORDING
        engine._ptt_active = True
        engine._absorb_ptt_key = True
        engine._audio_capture = MagicMock()
        engine._audio_capture.stop.return_value = None

        release_state = int(DEFAULT_PTT_MODIFIERS) | int(IBus.ModifierType.RELEASE_MASK)

        with patch.object(engine, "update_preedit_text"), patch.object(
            engine, "update_property"
        ):
            result = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 0, release_state)

        # The absorb check fires first (keyval matches, is_release) → clears flag
        # AND stops recording because _ptt_active was True
        assert result is True
        assert engine._absorb_ptt_key is False
        assert engine._ptt_active is False
        assert engine._state == EngineState.IDLE  # stop.return_value=None → IDLE

    def test_absorb_release_stops_recording(self):
        """Absorb guard release with ptt_active stops recording (the bug fix).

        This is the exact scenario from the real log:
        1. Ctrl+Space starts recording, sets absorb=True
        2. Auto-repeats flood in with Ctrl+Space (state=4)
        3. Space release (state=RELEASE_MASK|4) hits absorb guard first
        4. Absorb guard must ALSO stop recording
        """
        engine = _make_engine()
        engine._state = EngineState.RECORDING
        engine._ptt_active = True
        engine._ptt_source = "ibus"
        engine._absorb_ptt_key = True
        mock_segment = MagicMock()
        mock_segment.duration_ms = 2000
        engine._audio_capture = MagicMock()
        engine._audio_capture.stop.return_value = mock_segment

        release_state = int(DEFAULT_PTT_MODIFIERS) | int(IBus.ModifierType.RELEASE_MASK)

        with (
            patch.object(engine, "update_preedit_text"),
            patch.object(engine, "update_property"),
        ):
            result = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, release_state)

        assert result is True
        assert engine._absorb_ptt_key is False
        assert engine._ptt_active is False
        assert engine._ptt_source is None
        assert engine._state == EngineState.TRANSCRIBING

    def test_portal_release_schedules_timeout(self):
        """Global PTT release schedules a safety timeout for absorb flag."""
        engine = _make_engine()
        engine._state = EngineState.RECORDING
        engine._ptt_active = True
        engine._ptt_source = "global"
        engine._absorb_ptt_key = True
        engine._audio_capture = MagicMock()
        engine._audio_capture.stop.return_value = None

        with (
            patch.object(engine, "update_preedit_text"),
            patch.object(engine, "update_property"),
            patch("speak2type.engine.GLib.timeout_add") as mock_timeout,
        ):
            engine._on_global_ptt_release()

        mock_timeout.assert_called_once()
        assert mock_timeout.call_args[0][0] == 1000  # 1 second timeout

    def test_timeout_callback_clears_absorb(self):
        """The timeout callback clears the absorb flag."""
        engine = _make_engine()
        engine._absorb_ptt_key = True
        engine._absorb_timeout_id = 42

        result = engine._absorb_timeout_cb()

        assert engine._absorb_ptt_key is False
        assert engine._absorb_timeout_id == 0
        assert result == GLib.SOURCE_REMOVE

    def test_full_scenario_bare_spaces_blocked(self):
        """End-to-end: Ctrl+Space PTT, portal releases first, bare spaces absorbed.

        Reproduces the exact bug from issue #7:
        1. Ctrl+Space pressed → IBus starts PTT
        2. Portal fires activated (no-op, already recording)
        3. Portal fires deactivated → recording stops
        4. User releases Ctrl → Ctrl_L release passes through
        5. Bare Space auto-repeat → ALL consumed by absorb
        6. User releases Space → absorb cleared
        """
        engine = _make_engine()
        engine._state = EngineState.IDLE
        engine._recording_disabled = False
        engine._audio_capture = MagicMock()
        engine._audio_capture.is_setup = True
        engine._audio_capture.start.return_value = True
        mock_segment = MagicMock()
        mock_segment.duration_ms = 1000  # 1 second — above 200ms threshold
        engine._audio_capture.stop.return_value = mock_segment

        ptt_mod = int(DEFAULT_PTT_MODIFIERS)
        release_mask = int(IBus.ModifierType.RELEASE_MASK)

        with (
            patch.object(engine, "update_preedit_text"),
            patch.object(engine, "update_property"),
            patch("speak2type.engine.GLib.timeout_add"),
        ):
            # Step 1: Mod+Space press → starts recording
            r = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, ptt_mod)
            assert r is True
            assert engine._state == EngineState.RECORDING
            assert engine._absorb_ptt_key is True

            # Step 2: A few Mod+Space repeats
            for _ in range(5):
                r = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, ptt_mod)
                assert r is True

            # Step 3: Portal releases → recording stops
            engine._on_global_ptt_release()
            assert engine._state == EngineState.TRANSCRIBING
            assert engine._ptt_active is False

            # Step 4: Modifier release — not the PTT key, should pass through
            r = engine.do_process_key_event(IBus.KEY_Alt_L, 56, ptt_mod | release_mask)
            assert r is False

            # Step 5: Bare Space auto-repeats — ALL must be consumed
            for _ in range(20):
                r = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, 0)
                assert r is True, "Bare space must be consumed by absorb"

            # Step 6: Space release → absorb cleared
            r = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, release_mask)
            assert r is True
            assert engine._absorb_ptt_key is False

            # Step 7: Next bare space should pass through (normal typing)
            r = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, 0)
            assert r is False

    def test_no_retrigger_after_absorb_timeout(self):
        """Auto-repeat events must not start a new recording after timeout expires.

        Reproduces: absorb timeout fires while PTT key is still held from
        a previous session.  Without the fix, the next auto-repeat event
        matches the PTT combo and starts an unwanted recording.
        """
        engine = _make_engine()
        engine._state = EngineState.IDLE
        engine._recording_disabled = False
        engine._audio_capture = MagicMock()
        engine._audio_capture.is_setup = True
        engine._audio_capture.start.return_value = True
        mock_segment = MagicMock()
        mock_segment.duration_ms = 1000
        engine._audio_capture.stop.return_value = mock_segment

        ptt_mod = int(DEFAULT_PTT_MODIFIERS)
        release_mask = int(IBus.ModifierType.RELEASE_MASK)

        with (
            patch.object(engine, "update_preedit_text"),
            patch.object(engine, "update_property"),
            patch("speak2type.engine.GLib.timeout_add"),
        ):
            # Step 1: PTT activates
            r = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, ptt_mod)
            assert engine._state == EngineState.RECORDING
            assert engine._ptt_key_physically_released is False

            # Step 2: Portal releases → recording stops
            engine._on_global_ptt_release()
            assert engine._state == EngineState.TRANSCRIBING

            # Step 3: Simulate absorb timeout expiring
            engine._absorb_timeout_cb()
            assert engine._absorb_ptt_key is False
            # Key still not physically released
            assert engine._ptt_key_physically_released is False

            # Step 4: Auto-repeat events with PTT combo — must NOT start recording
            for _ in range(10):
                r = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, ptt_mod)
                assert r is True, "Auto-repeat must be consumed, not start recording"
            # Engine must still be in TRANSCRIBING (or whatever it was), not RECORDING
            assert engine._state != EngineState.RECORDING

            # Step 5: Physical release → flag cleared
            r = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, ptt_mod | release_mask)
            # The regular release path checks _ptt_active, which is False after portal release
            # The absorb guard is also cleared. So this should pass through.
            assert engine._ptt_key_physically_released is True

            # Step 6: NOW a fresh PTT press should work
            # First we need the engine back to IDLE
            engine._state = EngineState.IDLE
            r = engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 57, ptt_mod)
            assert r is True
            assert engine._state == EngineState.RECORDING


# ---------------------------------------------------------------------------
# Leaked space counting
# ---------------------------------------------------------------------------


class TestLeakedSpaceCount:
    """PTT key repeats during RECORDING increment _leaked_space_count."""

    def test_no_leak_count_in_idle(self):
        """Key press in IDLE starts recording but does not count as a leak."""
        engine = _make_engine()
        engine._state = EngineState.IDLE
        engine._recording_disabled = False
        engine._audio_capture = MagicMock()
        engine._audio_capture.is_setup = True
        engine._audio_capture.start.return_value = True

        with patch.object(engine, "update_preedit_text"):
            with patch.object(engine, "update_property"):
                engine.do_process_key_event(
                    DEFAULT_PTT_KEYVAL,
                    0,
                    int(DEFAULT_PTT_MODIFIERS),
                )

        assert engine._state == EngineState.RECORDING
        assert engine._leaked_space_count == 0

    def test_repeat_increments_leak_count(self):
        """Key repeat during RECORDING increments leaked count."""
        engine = _make_engine()
        engine._state = EngineState.RECORDING
        engine._ptt_active = True
        engine._ptt_source = "ibus"

        result = engine.do_process_key_event(
            DEFAULT_PTT_KEYVAL,
            0,
            int(DEFAULT_PTT_MODIFIERS),
        )

        assert result is True
        assert engine._leaked_space_count == 1

    def test_multiple_repeats_accumulate(self):
        """Multiple key repeats accumulate the leak count."""
        engine = _make_engine()
        engine._state = EngineState.RECORDING
        engine._ptt_active = True
        engine._ptt_source = "ibus"

        for _ in range(15):
            engine.do_process_key_event(
                DEFAULT_PTT_KEYVAL,
                0,
                int(DEFAULT_PTT_MODIFIERS),
            )

        assert engine._leaked_space_count == 15

    def test_leak_count_resets_on_recording_start(self):
        """Starting a new recording resets the leaked count."""
        engine = _make_engine()
        engine._leaked_space_count = 42
        engine._state = EngineState.IDLE
        engine._recording_disabled = False
        engine._audio_capture = MagicMock()
        engine._audio_capture.is_setup = True
        engine._audio_capture.start.return_value = True

        with patch.object(engine, "update_preedit_text"):
            with patch.object(engine, "update_property"):
                engine._start_recording()

        assert engine._leaked_space_count == 0

    def test_release_does_not_increment(self):
        """Key release does not increment the leak count."""
        engine = _make_engine()
        engine._state = EngineState.RECORDING
        engine._ptt_active = True
        # Mock audio capture to return None segment (short recording)
        engine._audio_capture = MagicMock()
        engine._audio_capture.stop.return_value = None

        release_state = int(DEFAULT_PTT_MODIFIERS) | int(IBus.ModifierType.RELEASE_MASK)

        with patch.object(engine, "update_preedit_text"):
            with patch.object(engine, "update_property"):
                engine.do_process_key_event(DEFAULT_PTT_KEYVAL, 0, release_state)

        assert engine._leaked_space_count == 0


# ---------------------------------------------------------------------------
# _type_text_unfocused
# ---------------------------------------------------------------------------


class TestTypeTextUnfocused:
    """_type_text_unfocused dispatches to the correct tool or falls back."""

    def test_wayland_dispatches_wtype(self):
        """On Wayland with wtype available, uses _paste_with_wtype."""
        engine = _make_engine()
        engine._leaked_space_count = 3

        with (
            patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}),
            patch("speak2type.engine.shutil.which", side_effect=lambda t: t == "wtype"),
            patch.object(engine, "_copy_to_clipboard"),
            patch.object(engine, "_paste_with_wtype") as mock_wtype,
        ):
            engine._type_text_unfocused("hello world")

        mock_wtype.assert_called_once_with(3)
        assert engine._leaked_space_count == 0

    def test_x11_dispatches_xdotool(self):
        """On X11 with xdotool available, uses _paste_with_xdotool."""
        engine = _make_engine()
        engine._leaked_space_count = 5

        with (
            patch.dict("os.environ", {"XDG_SESSION_TYPE": "x11"}),
            patch("speak2type.engine.shutil.which", side_effect=lambda t: t == "xdotool"),
            patch.object(engine, "_copy_to_clipboard"),
            patch.object(engine, "_paste_with_xdotool") as mock_xdotool,
        ):
            engine._type_text_unfocused("hello world")

        mock_xdotool.assert_called_once_with(5)

    def test_wayland_without_wtype_falls_back_to_xdotool(self):
        """On Wayland without wtype, falls back to xdotool."""
        engine = _make_engine()

        def which_side_effect(name):
            return "/usr/bin/xdotool" if name == "xdotool" else None

        with (
            patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}),
            patch("speak2type.engine.shutil.which", side_effect=which_side_effect),
            patch.object(engine, "_copy_to_clipboard"),
            patch.object(engine, "_paste_with_xdotool") as mock_xdotool,
        ):
            engine._type_text_unfocused("test")

        mock_xdotool.assert_called_once()

    def test_no_tools_falls_back_to_clipboard(self):
        """Without wtype or xdotool, copies to clipboard only."""
        engine = _make_engine()

        with (
            patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}),
            patch("speak2type.engine.shutil.which", return_value=None),
            patch.object(engine, "_copy_to_clipboard") as mock_clip,
        ):
            engine._type_text_unfocused("fallback text")

        mock_clip.assert_called_once_with("fallback text")

    def test_always_copies_to_clipboard(self):
        """Regardless of paste tool, always copies to clipboard first."""
        engine = _make_engine()

        with (
            patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}),
            patch("speak2type.engine.shutil.which", return_value="/usr/bin/wtype"),
            patch.object(engine, "_copy_to_clipboard") as mock_clip,
            patch("speak2type.engine.subprocess.run"),
        ):
            engine._type_text_unfocused("text")

        mock_clip.assert_called_once_with("text")


# ---------------------------------------------------------------------------
# _paste_with_wtype
# ---------------------------------------------------------------------------


class TestPasteWithWtype:
    """wtype command construction."""

    def test_no_leaked_spaces(self):
        """With zero leaked spaces, just pastes."""
        engine = _make_engine()

        with patch("speak2type.engine.subprocess.run") as mock_run:
            engine._paste_with_wtype(0)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["wtype", "-M", "ctrl", "-k", "v", "-m", "ctrl"]

    def test_with_leaked_spaces(self):
        """Leaked spaces produce Shift+Left selection before paste."""
        engine = _make_engine()

        with patch("speak2type.engine.subprocess.run") as mock_run:
            engine._paste_with_wtype(3)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "wtype"
        # Should have Shift+Left×3 for selection + 1 v for paste = 4
        assert cmd.count("-k") == 4
        # Shift modifier wrapping for selection
        assert "shift" in cmd
        # Paste at end: -M ctrl -k v -m ctrl
        assert cmd[-6:] == ["-M", "ctrl", "-k", "v", "-m", "ctrl"]

    def test_subprocess_error_logged(self):
        """subprocess errors are caught and logged, not raised."""
        engine = _make_engine()

        with patch(
            "speak2type.engine.subprocess.run",
            side_effect=subprocess.TimeoutExpired("wtype", 10),
        ):
            # Should not raise
            engine._paste_with_wtype(0)


# ---------------------------------------------------------------------------
# _paste_with_xdotool
# ---------------------------------------------------------------------------


class TestPasteWithXdotool:
    """xdotool command construction."""

    def test_no_leaked_spaces(self):
        """With zero leaked spaces, just pastes."""
        engine = _make_engine()

        with patch("speak2type.engine.subprocess.run") as mock_run:
            engine._paste_with_xdotool(0)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["xdotool", "key", "ctrl+v"]

    def test_with_leaked_spaces(self):
        """Leaked spaces produce Shift+Left keys before paste."""
        engine = _make_engine()

        with patch("speak2type.engine.subprocess.run") as mock_run:
            engine._paste_with_xdotool(4)

        assert mock_run.call_count == 2

        # First call: selection
        select_cmd = mock_run.call_args_list[0][0][0]
        assert select_cmd[0] == "xdotool"
        assert select_cmd.count("shift+Left") == 4

        # Second call: paste
        paste_cmd = mock_run.call_args_list[1][0][0]
        assert paste_cmd == ["xdotool", "key", "ctrl+v"]

    def test_subprocess_error_logged(self):
        """subprocess errors are caught and logged, not raised."""
        engine = _make_engine()

        with patch(
            "speak2type.engine.subprocess.run",
            side_effect=subprocess.TimeoutExpired("xdotool", 10),
        ):
            # Should not raise
            engine._paste_with_xdotool(0)


# ---------------------------------------------------------------------------
# Integration: _on_transcription_result for unfocused apps
# ---------------------------------------------------------------------------


class TestTranscriptionResultUnfocused:
    """When _has_real_focus=False, result goes through _type_text_unfocused."""

    def test_unfocused_calls_type_text_unfocused(self):
        """Transcription result dispatches to _type_text_unfocused."""
        engine = _make_engine()
        engine._has_real_focus = False
        engine._state = EngineState.TRANSCRIBING

        result = TranscriptResult(text="hello world")

        with (
            patch.object(engine, "_type_text_unfocused") as mock_type,
            patch.object(engine, "update_property"),
        ):
            engine._on_transcription_result(result)

        mock_type.assert_called_once_with("hello world")

    def test_focused_still_uses_commit_text(self):
        """Transcription result with real focus uses commit_text."""
        engine = _make_engine()
        engine._has_real_focus = True
        engine._state = EngineState.TRANSCRIBING

        result = TranscriptResult(text="hello")

        with (
            patch.object(engine, "commit_text") as mock_commit,
            patch.object(engine, "update_preedit_text"),
            patch.object(engine, "update_property"),
        ):
            engine._on_transcription_result(result)

        mock_commit.assert_called_once()
