"""speak2type IBus engine with push-to-talk support."""

import logging
import os
import shutil
import subprocess
import sys

import gi

gi.require_version("IBus", "1.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")

from gi.repository import IBus, GLib, Gio, GObject

from .types import EngineState, RecordMode, AudioSource, TranscriptResult
from .audio_capture import AudioCapture
from .worker import TranscriptionWorker
from .backends import get_registry, register_default_backends
from .global_hotkey import GlobalHotkeyListener

LOG = logging.getLogger(__name__)

# Default push-to-talk hotkey: Alt+Space
DEFAULT_PTT_KEYVAL = IBus.KEY_space
DEFAULT_PTT_MODIFIERS = IBus.ModifierType.MOD1_MASK  # Alt key

# Mapping from GTK accelerator modifier names to IBus modifier masks
_MODIFIER_MAP = {
    "alt": IBus.ModifierType.MOD1_MASK,
    "mod1": IBus.ModifierType.MOD1_MASK,
    "ctrl": IBus.ModifierType.CONTROL_MASK,
    "control": IBus.ModifierType.CONTROL_MASK,
    "shift": IBus.ModifierType.SHIFT_MASK,
    "super": IBus.ModifierType.MOD4_MASK,
    "mod4": IBus.ModifierType.MOD4_MASK,
}


def parse_accelerator(accel: str) -> tuple[int, int]:
    """Parse a GTK accelerator string into (keyval, modifiers).

    Examples: '<Alt>space', '<Ctrl><Shift>r', '<Super>d'

    Returns:
        Tuple of (IBus keyval, IBus modifier mask).
        Falls back to (DEFAULT_PTT_KEYVAL, DEFAULT_PTT_MODIFIERS) on parse error.
    """
    modifiers = 0
    remaining = accel.strip()

    # Extract <Modifier> tokens
    while remaining.startswith("<"):
        end = remaining.find(">")
        if end == -1:
            break
        mod_name = remaining[1:end].lower()
        if mod_name in _MODIFIER_MAP:
            modifiers |= _MODIFIER_MAP[mod_name]
        else:
            LOG.warning("Unknown modifier in accelerator '%s': %s", accel, mod_name)
        remaining = remaining[end + 1:]

    # Remaining is the key name
    key_name = remaining.strip()
    if not key_name:
        LOG.warning("No key name in accelerator '%s'", accel)
        return DEFAULT_PTT_KEYVAL, DEFAULT_PTT_MODIFIERS

    keyval = IBus.keyval_from_name(key_name)
    if keyval == 0:
        LOG.warning("Unknown key name in accelerator '%s': %s", accel, key_name)
        return DEFAULT_PTT_KEYVAL, DEFAULT_PTT_MODIFIERS

    return keyval, modifiers


class Speak2TypeEngine(IBus.Engine):
    """IBus engine for speech-to-text with push-to-talk support."""

    __gtype_name__ = "Speak2TypeEngine"

    def __init__(self, bus: IBus.Bus, object_path: str) -> None:
        """Initialize the engine.

        Args:
            bus: IBus bus connection.
            object_path: D-Bus object path.
        """
        # Initialize with focus-id capability if available
        if hasattr(IBus.Engine.props, "has_focus_id"):
            super().__init__(
                connection=bus.get_connection(),
                object_path=object_path,
                has_focus_id=True,
            )
            LOG.info("Engine initialized with focus-id capability")
        else:
            super().__init__(
                connection=bus.get_connection(),
                object_path=object_path,
            )
            LOG.info("Engine initialized without focus-id capability")

        # State machine
        self._state = EngineState.IDLE
        self._recording_disabled = False  # Privacy: disabled in password fields
        self._ptt_active = False  # Tracks if PTT key is held (for release detection)
        self._has_real_focus = False  # True when focused on an IBus-aware input context
        self._ptt_source: str | None = None  # 'ibus' or 'global' when PTT is active

        # Settings (optional - schema may not be installed)
        self._settings = None
        schema_source = Gio.SettingsSchemaSource.get_default()
        if schema_source and schema_source.lookup("org.freedesktop.ibus.engine.stt", True):
            self._settings = Gio.Settings.new("org.freedesktop.ibus.engine.stt")
            LOG.info("Loaded GSettings schema")
        else:
            LOG.warning("GSettings schema not installed, using defaults")

        self._record_mode = RecordMode.PUSH_TO_TALK
        self._ptt_keyval = DEFAULT_PTT_KEYVAL
        self._ptt_modifiers = DEFAULT_PTT_MODIFIERS
        if self._settings:
            self._load_settings()

        # Audio capture
        audio_source = AudioSource.AUTO
        if self._settings:
            audio_source_str = self._settings.get_string("audio-source")
            audio_source = AudioSource(audio_source_str) if audio_source_str else AudioSource.AUTO
        self._audio_capture = AudioCapture(audio_source=audio_source)

        # Initialize worker to None (set in _setup_backend)
        self._worker = None

        # Set up backend from registry
        self._setup_backend()

        # Global hotkey listener (XDG Desktop Portal)
        self._global_hotkey = GlobalHotkeyListener(
            on_press=self._on_global_ptt_press,
            on_release=self._on_global_ptt_release,
            accelerator=self._get_accelerator_string(),
        )

        # Listen for hotkey setting changes
        if self._settings:
            self._settings.connect("changed::ptt-hotkey", self._on_hotkey_changed)

        # Properties for IBus panel
        self._prop_list = self._create_properties()

        # Pending text for commit
        self._pending_text = ""

        LOG.info("Speak2TypeEngine created")

    def _setup_backend(self) -> None:
        """Set up the speech recognition backend and worker thread.

        If no backend is available (e.g. fresh install before the user
        configures one via preferences), the engine starts without a
        backend.  Dictation attempts will show a guidance message instead
        of silently producing placeholder text.

        See .aisteering/policy-exceptions.md — ENGINE_NO_BACKEND.
        """
        # Register default backends
        register_default_backends()

        # Get configured backend from settings (default to parakeet)
        backend_id = "parakeet"
        if self._settings:
            backend_id = self._settings.get_string("backend") or "parakeet"
        registry = get_registry()

        # Try to activate the configured backend
        if not registry.set_current(backend_id):
            available = [b for b in registry.available_backends if b != "placeholder"]
            if available:
                # A different backend is available — try the first one
                registry.set_current(available[0])
                LOG.warning(
                    "Configured backend '%s' not available, using '%s'",
                    backend_id, available[0],
                )
            else:
                LOG.warning(
                    "No speech recognition backend installed. "
                    "Open speak2type settings to install one."
                )
                return

        backend = registry.current
        LOG.info("Using backend: %s (%s)", backend.id, backend.name)

        # Create worker thread with the backend
        self._worker = TranscriptionWorker(
            backend=backend,
            on_result=self._on_transcription_result,
            on_error=self._on_transcription_error,
        )

    def _on_transcription_error(self, error: Exception) -> None:
        """Handle transcription error (called in main loop)."""
        LOG.error("Transcription error: %s", error)

        # Clear preedit (only relevant in IBus-aware apps)
        if self._has_real_focus:
            self.update_preedit_text(
                IBus.Text.new_from_string(""),
                0,
                False,
            )

        self._transition_to(EngineState.IDLE)

    def _load_settings(self) -> None:
        """Load settings from GSettings."""
        try:
            mode = self._settings.get_string("record-mode")
            if mode:
                self._record_mode = RecordMode(mode)
        except Exception as e:
            LOG.warning("Failed to load record-mode setting: %s", e)

        try:
            hotkey = self._settings.get_string("ptt-hotkey")
            if hotkey and hotkey != "None":
                self._ptt_keyval, self._ptt_modifiers = parse_accelerator(hotkey)
                LOG.info(
                    "PTT hotkey: '%s' -> keyval=%d, modifiers=%d",
                    hotkey, self._ptt_keyval, self._ptt_modifiers,
                )
        except Exception as e:
            LOG.warning("Failed to load ptt-hotkey setting: %s", e)

    def _create_properties(self) -> IBus.PropList:
        """Create IBus properties for the panel."""
        props = IBus.PropList()

        # Toggle recording button
        props.append(
            IBus.Property(
                key="toggle-recording",
                label=IBus.Text.new_from_string("Recognition off"),
                icon="audio-input-microphone",
                type=IBus.PropType.TOGGLE,
                state=IBus.PropState.UNCHECKED,
                tooltip=IBus.Text.new_from_string("Toggle speech recognition"),
            )
        )

        # Mode indicator
        props.append(
            IBus.Property(
                key="mode",
                label=IBus.Text.new_from_string("Push-to-talk (Alt+Space)"),
                type=IBus.PropType.NORMAL,
                sensitive=False,
            )
        )

        return props

    def _update_state_ui(self) -> None:
        """Update UI to reflect current state."""
        if self._state == EngineState.RECORDING:
            label = "Recording..."
            state = IBus.PropState.CHECKED
        elif self._state == EngineState.TRANSCRIBING:
            label = "Transcribing..."
            state = IBus.PropState.CHECKED
        else:
            label = "Recognition off"
            state = IBus.PropState.UNCHECKED

        prop = IBus.Property(
            key="toggle-recording",
            label=IBus.Text.new_from_string(label),
            icon="audio-input-microphone",
            type=IBus.PropType.TOGGLE,
            state=state,
            sensitive=not self._recording_disabled,
        )
        self.update_property(prop)

    def _transition_to(self, new_state: EngineState) -> None:
        """Transition to a new state."""
        old_state = self._state
        self._state = new_state
        LOG.debug("State transition: %s -> %s", old_state.name, new_state.name)
        self._update_state_ui()

    def _start_recording(self) -> bool:
        """Start recording audio.

        Returns:
            True if recording started successfully.
        """
        if self._state != EngineState.IDLE:
            LOG.warning("Cannot start recording in state %s", self._state.name)
            return False

        if self._recording_disabled:
            LOG.info("Recording disabled (privacy mode)")
            return False

        # Ensure audio capture is set up (only once, not every recording)
        if not self._audio_capture.is_setup:
            if not self._audio_capture.setup(on_error=self._on_audio_error):
                LOG.error("Failed to set up audio capture")
                return False

        if not self._audio_capture.start():
            LOG.error("Failed to start audio capture")
            return False

        self._transition_to(EngineState.RECORDING)

        # Show recording indicator (only visible in IBus-aware apps)
        if self._has_real_focus:
            self.update_preedit_text(
                IBus.Text.new_from_string("🎙️ Recording..."),
                0,
                True,
            )

        return True

    def _stop_recording(self) -> None:
        """Stop recording and start transcription."""
        if self._state != EngineState.RECORDING:
            LOG.warning("Cannot stop recording in state %s", self._state.name)
            return

        # Stop audio capture and get segment
        segment = self._audio_capture.stop()

        # Clear preedit (only relevant in IBus-aware apps)
        if self._has_real_focus:
            self.update_preedit_text(
                IBus.Text.new_from_string(""),
                0,
                False,
            )

        if segment is None or segment.duration_ms < 200:
            LOG.info("No audio or too short, returning to idle")
            self._transition_to(EngineState.IDLE)
            return

        self._transition_to(EngineState.TRANSCRIBING)

        # Show transcribing indicator (only visible in IBus-aware apps)
        if self._has_real_focus:
            self.update_preedit_text(
                IBus.Text.new_from_string("⏳ Transcribing..."),
                0,
                True,
            )

        # Submit to worker
        if self._worker:
            locale = "en_US"
            if self._settings:
                locale = self._settings.get_string("locale") or "en_US"
            self._worker.submit(segment, locale_hint=locale)
        else:
            LOG.error("No backend installed — open speak2type settings to configure one")
            self.update_preedit_text(
                IBus.Text.new_from_string("No backend — open speak2type settings"),
                0,
                True,
            )
            GLib.timeout_add(3000, self._clear_no_backend_message)

    def _clear_no_backend_message(self) -> bool:
        """Clear the 'no backend' preedit message and return to idle."""
        self.update_preedit_text(IBus.Text.new_from_string(""), 0, False)
        self._transition_to(EngineState.IDLE)
        return GLib.SOURCE_REMOVE

    def _clear_error_preedit(self) -> bool:
        """Clear an error preedit message after timeout."""
        self.update_preedit_text(IBus.Text.new_from_string(""), 0, False)
        return GLib.SOURCE_REMOVE

    def _on_transcription_result(self, result: TranscriptResult) -> None:
        """Handle transcription result (called in main loop)."""
        # Clear preedit (only relevant in IBus-aware apps)
        if self._has_real_focus:
            self.update_preedit_text(
                IBus.Text.new_from_string(""),
                0,
                False,
            )

        if result.error:
            LOG.error("Transcription failed: %s", result.error)
            if self._has_real_focus:
                self.update_preedit_text(
                    IBus.Text.new_from_string(f"Error: {result.error}"),
                    0,
                    True,
                )
                GLib.timeout_add(3000, self._clear_error_preedit)
            self._transition_to(EngineState.IDLE)
            return

        if result.text:
            self._transition_to(EngineState.COMMITTING)
            if self._has_real_focus:
                self.commit_text(IBus.Text.new_from_string(result.text))
                LOG.debug("Committed text to input: '%s'", result.text)
            else:
                self._copy_to_clipboard(result.text)
                LOG.debug("Copied text to clipboard: '%s'", result.text)

        self._transition_to(EngineState.IDLE)

    def _copy_to_clipboard(self, text: str) -> None:
        """Copy text to the system clipboard."""
        session_type = os.environ.get("XDG_SESSION_TYPE", "")

        if session_type == "wayland" and shutil.which("wl-copy"):
            cmd = ["wl-copy", "--", text]
        elif shutil.which("xclip"):
            cmd = ["xclip", "-selection", "clipboard"]
        else:
            LOG.error("No clipboard tool found (install wl-clipboard or xclip)")
            return

        try:
            proc = subprocess.run(
                cmd,
                input=text if "xclip" in cmd[0] else None,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode != 0:
                LOG.error("Clipboard copy failed: %s", proc.stderr)
        except Exception as e:
            LOG.error("Clipboard copy error: %s", e)

    def _on_audio_error(self, error: str) -> None:
        """Handle audio capture error."""
        LOG.error("Audio error: %s", error)
        self._transition_to(EngineState.IDLE)

    # ------------------------------------------------------------------
    # Global hotkey (XDG Desktop Portal) callbacks
    # ------------------------------------------------------------------

    def _get_accelerator_string(self) -> str:
        """Get the PTT hotkey as a GTK accelerator string from settings."""
        if self._settings:
            accel = self._settings.get_string("ptt-hotkey")
            if accel and accel != "None":
                return accel
        return "<Alt>space"

    def _on_global_ptt_press(self) -> None:
        """Handle global PTT key press (from portal)."""
        if self._state == EngineState.IDLE and not self._recording_disabled:
            self._ptt_active = True
            self._ptt_source = "global"
            self._start_recording()
            LOG.info("Global PTT activated")

    def _on_global_ptt_release(self) -> None:
        """Handle global PTT key release (from portal)."""
        if self._ptt_active and self._state == EngineState.RECORDING:
            self._ptt_active = False
            self._ptt_source = None
            self._stop_recording()
            LOG.info("Global PTT released")

    def _on_hotkey_changed(self, settings: Gio.Settings, key: str) -> None:
        """Handle PTT hotkey change from settings."""
        accel = settings.get_string(key)
        if accel and accel != "None":
            self._ptt_keyval, self._ptt_modifiers = parse_accelerator(accel)
            self._global_hotkey.update_shortcut(accel)
            LOG.info("PTT hotkey updated: %s", accel)

    def _is_ptt_key(self, keyval: int, modifiers: int) -> bool:
        """Check if the key event matches the push-to-talk hotkey.

        Args:
            keyval: Key value from IBus.
            modifiers: Modifier mask from IBus.

        Returns:
            True if this is the PTT key.
        """
        # Mask out release and other irrelevant modifiers
        relevant_mods = modifiers & (
            IBus.ModifierType.SHIFT_MASK
            | IBus.ModifierType.CONTROL_MASK
            | IBus.ModifierType.MOD1_MASK  # Alt
            | IBus.ModifierType.MOD4_MASK  # Super
        )

        return keyval == self._ptt_keyval and relevant_mods == self._ptt_modifiers

    # IBus Engine overrides

    def do_process_key_event(
        self, keyval: int, keycode: int, state: int
    ) -> bool:
        """Handle key events for push-to-talk.

        Args:
            keyval: Key value.
            keycode: Hardware key code.
            state: Modifier state.

        Returns:
            True if the key event was handled.
        """
        is_release = bool(state & IBus.ModifierType.RELEASE_MASK)
        LOG.debug("KEY EVENT: keyval=%d (%s), keycode=%d, state=%d, release=%s",
                  keyval, IBus.keyval_name(keyval), keycode, state, is_release)

        # Check for push-to-talk hotkey
        relevant_mods = state & (
            IBus.ModifierType.SHIFT_MASK
            | IBus.ModifierType.CONTROL_MASK
            | IBus.ModifierType.MOD1_MASK  # Alt
            | IBus.ModifierType.MOD4_MASK  # Super
        )
        LOG.debug("PTT check: keyval=%d (want %d), mods=%d (want %d), state=%s",
                  keyval, self._ptt_keyval, relevant_mods, self._ptt_modifiers, self._state)
        if self._record_mode == RecordMode.PUSH_TO_TALK:
            # Check for PTT activation (press with correct modifiers)
            if not is_release and self._is_ptt_key(keyval, state):
                # Key pressed - start recording or consume repeat
                if self._state == EngineState.IDLE:
                    self._ptt_active = True
                    self._ptt_source = "ibus"
                    self._start_recording()
                    LOG.debug("PTT activated (IBus)")
                # Always consume press (including repeats) to prevent spaces
                return True

            # Check for PTT release - only need keyval match (modifiers may differ)
            # User often releases Alt before Space, so we can't require modifier match
            if is_release and keyval == self._ptt_keyval and self._ptt_active:
                LOG.debug("PTT released (keyval match, ptt_active=True)")
                self._ptt_active = False
                self._ptt_source = None
                if self._state == EngineState.RECORDING:
                    self._stop_recording()
                # Consume release to prevent space from leaking
                return True

        # Let other keys pass through
        return False

    def do_set_content_type(self, purpose: int, hints: int) -> None:
        """Handle content type changes for privacy.

        Disable recording in password and PIN fields.

        Args:
            purpose: IBus.InputPurpose value.
            hints: IBus.InputHints value.
        """
        # Check for sensitive input types
        sensitive_purposes = {
            IBus.InputPurpose.PASSWORD,
            IBus.InputPurpose.PIN,
        }

        if purpose in sensitive_purposes:
            LOG.info("Privacy mode: recording disabled (purpose=%d)", purpose)
            self._recording_disabled = True

            # Stop any ongoing recording
            if self._state == EngineState.RECORDING:
                self._audio_capture.stop()
                self._transition_to(EngineState.IDLE)
        else:
            self._recording_disabled = False

        self._update_state_ui()

    def do_enable(self) -> None:
        """Called when the engine is enabled."""
        LOG.info("Engine enabled")

        # Set up audio capture
        self._audio_capture.setup(on_error=self._on_audio_error)

        # Start worker thread
        if self._worker:
            self._worker.start()

        # Set up global hotkey (portal-based, for non-IBus apps)
        if not self._global_hotkey.setup():
            LOG.warning("Global hotkey not available (portal missing?)")

        # Register properties
        self.register_properties(self._prop_list)
        self._update_state_ui()

    def do_disable(self) -> None:
        """Called when the engine is disabled."""
        LOG.info("Engine disabled")

        # Reset PTT state
        self._ptt_active = False
        self._ptt_source = None

        # Stop any ongoing recording
        if self._state == EngineState.RECORDING:
            self._audio_capture.stop()

        self._transition_to(EngineState.IDLE)

        # Tear down resources symmetrically with do_enable()
        self._global_hotkey.teardown()
        if self._worker:
            self._worker.stop()
        self._audio_capture.destroy()

    def do_focus_in(self) -> None:
        """Called when focus enters an input context."""
        LOG.info("FOCUS IN - IBus-aware app has focus")
        self._has_real_focus = True
        self.register_properties(self._prop_list)
        self._update_state_ui()

    def do_focus_out(self) -> None:
        """Called when focus leaves an input context."""
        LOG.info("FOCUS OUT - lost focus")
        self._has_real_focus = False

        # Only cancel IBus-triggered recordings on focus loss;
        # global-hotkey recordings should survive focus changes.
        if self._ptt_source != "global":
            self._ptt_active = False
            if self._state == EngineState.RECORDING:
                self._audio_capture.stop()
                self._transition_to(EngineState.IDLE)

    def do_focus_in_id(self, object_path: str, client: str) -> None:
        """Called when focus enters with client info (Wayland)."""
        LOG.info("FOCUS IN ID: path=%s, client=%s", object_path, client)
        self._has_real_focus = client != "fake"
        self.register_properties(self._prop_list)
        self._update_state_ui()

    def do_focus_out_id(self, object_path: str) -> None:
        """Called when focus leaves with path info (Wayland)."""
        LOG.info("FOCUS OUT ID: path=%s", object_path)
        self._has_real_focus = False
        # Only cancel IBus-triggered recordings on focus loss
        if self._ptt_source != "global":
            self._ptt_active = False
            if self._state == EngineState.RECORDING:
                self._audio_capture.stop()
                self._transition_to(EngineState.IDLE)

    def do_reset(self) -> None:
        """Called to reset the engine state."""
        LOG.info("RESET")

        # Only cancel IBus-triggered recordings on reset
        if self._ptt_source != "global":
            self._ptt_active = False
            if self._state == EngineState.RECORDING:
                self._audio_capture.stop()
                self._transition_to(EngineState.IDLE)

    def do_property_activate(self, prop_name: str, state: int) -> None:
        """Handle property activation from the panel.

        Args:
            prop_name: Property name.
            state: Property state.
        """
        LOG.debug("Property activated: %s = %d", prop_name, state)

        if prop_name == "toggle-recording":
            if self._record_mode == RecordMode.TOGGLE:
                # Toggle mode: click to start/stop
                if state == IBus.PropState.CHECKED:
                    self._start_recording()
                else:
                    self._stop_recording()

    def do_destroy(self) -> None:
        """Clean up resources."""
        LOG.info("Engine destroying")

        self._global_hotkey.teardown()

        if self._worker:
            self._worker.stop()

        self._audio_capture.destroy()

        IBus.Engine.do_destroy(self)


class Speak2TypeEngineFactory(IBus.Factory):
    """Factory for creating Speak2Type engines."""

    __gtype_name__ = "Speak2TypeEngineFactory"

    def __init__(self, bus: IBus.Bus) -> None:
        """Initialize the factory.

        Args:
            bus: IBus bus connection.
        """
        self._bus = bus
        self._current_engine = None
        # Match upstream argument order: object_path first, then connection
        super().__init__(
            object_path=IBus.PATH_FACTORY,
            connection=bus.get_connection(),
        )
        LOG.info("Engine factory created at %s", IBus.PATH_FACTORY)

    def do_create_engine(self, engine_name: str) -> IBus.Engine | None:
        """Create a new engine instance.

        Args:
            engine_name: Name of the engine to create.

        Returns:
            New engine instance or None.
        """
        LOG.info("Creating engine for: %s", engine_name)
        if engine_name != "speak2type":
            LOG.warning("Unknown engine name: %s, delegating to parent", engine_name)
            return super().do_create_engine(engine_name)

        engine = Speak2TypeEngine(self._bus, "/org/freedesktop/IBus/speak2type")
        self._current_engine = engine
        LOG.info("Created engine at /org/freedesktop/IBus/speak2type")
        return engine


def _get_log_level_from_settings() -> int:
    """Read log level from GSettings, defaulting to WARNING."""
    try:
        schema_source = Gio.SettingsSchemaSource.get_default()
        if schema_source and schema_source.lookup(
            "org.freedesktop.ibus.engine.stt", True
        ):
            settings = Gio.Settings.new("org.freedesktop.ibus.engine.stt")
            level_str = settings.get_string("log-level").upper()
            return getattr(logging, level_str, logging.WARNING)
    except Exception:
        pass
    return logging.WARNING


def main() -> int:
    """Main entry point for the IBus engine."""
    # Set up logging to file
    log_file = os.path.expanduser("~/.cache/speak2type/engine.log")
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    log_level = _get_log_level_from_settings()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )

    LOG.info("speak2type engine starting")

    # Check if running in IBus mode (started by IBus daemon)
    ibus_mode = "--ibus" in sys.argv

    # Initialize IBus
    IBus.init()

    # Create bus connection
    bus = IBus.Bus()
    if not bus.is_connected():
        LOG.error("Cannot connect to IBus")
        return 1

    # Create factory FIRST - must be done before request_name
    factory = Speak2TypeEngineFactory(bus)
    # Register the engine type with the factory
    factory.add_engine("speak2type", GObject.type_from_name("Speak2TypeEngine"))
    LOG.info("Factory and engine type registered")

    # Different initialization based on how we were started
    if ibus_mode:
        # Started by IBus - just request name, IBus already knows about component
        LOG.info("Running in IBus mode, requesting name")
        bus.request_name("org.freedesktop.IBus.speak2type", 0)
    else:
        # Standalone mode - register component so IBus knows about us
        LOG.info("Running in standalone mode, registering component")
        component = IBus.Component(
            name="org.freedesktop.IBus.speak2type",
            description="Speech To Text Engine",
            version="0.1.0",
            license="GPL-3.0",
            author="speak2type contributors",
            homepage="https://github.com/speak2type/speak2type",
            textdomain="speak2type",
        )
        component.add_engine(
            IBus.EngineDesc(
                name="speak2type",
                longname="Speech To Text",
                description="Speech to text input method",
                language="en",
                license="GPL-3.0",
                author="speak2type contributors",
                icon="audio-input-microphone",
                layout="us",
            )
        )
        bus.register_component(component)

    # Start main loop
    LOG.info("Entering main loop")
    mainloop = GLib.MainLoop()

    # Handle SIGINT/SIGTERM
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 2, mainloop.quit)  # SIGINT
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 15, mainloop.quit)  # SIGTERM

    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass

    LOG.info("speak2type engine exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
