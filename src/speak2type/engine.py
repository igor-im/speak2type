"""speak2type IBus engine with push-to-talk support."""

import logging
import os
import sys

import gi

gi.require_version("IBus", "1.0")
gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")

from gi.repository import IBus, GLib, Gio

from .types import EngineState, RecordMode, AudioSource, TranscriptResult
from .audio_capture import AudioCapture
from .worker import TranscriptionWorker
from .backends import get_registry, register_default_backends

LOG = logging.getLogger(__name__)

# Default push-to-talk hotkey: Alt+Space
DEFAULT_PTT_KEYVAL = IBus.KEY_space
DEFAULT_PTT_MODIFIERS = IBus.ModifierType.MOD1_MASK  # Alt key


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

        # Settings
        self._settings = Gio.Settings.new("org.freedesktop.ibus.engine.stt")
        self._record_mode = RecordMode.PUSH_TO_TALK
        self._ptt_keyval = DEFAULT_PTT_KEYVAL
        self._ptt_modifiers = DEFAULT_PTT_MODIFIERS
        self._load_settings()

        # Audio capture
        audio_source_str = self._settings.get_string("audio-source")
        audio_source = AudioSource(audio_source_str) if audio_source_str else AudioSource.AUTO
        self._audio_capture = AudioCapture(audio_source=audio_source)

        # Set up backend from registry
        self._setup_backend()

        # Properties for IBus panel
        self._prop_list = self._create_properties()

        # Pending text for commit
        self._pending_text = ""

        LOG.info("Speak2TypeEngine created")

    def _setup_backend(self) -> None:
        """Set up the speech recognition backend and worker thread."""
        # Register default backends
        register_default_backends()

        # Get configured backend from settings
        backend_id = self._settings.get_string("backend") or "vosk"
        registry = get_registry()

        # Try to set the configured backend
        if not registry.set_current(backend_id):
            LOG.warning("Configured backend '%s' not available, using fallback", backend_id)
            # Try alternatives
            for alt_id in ["vosk", "whisper", "placeholder"]:
                if registry.set_current(alt_id):
                    break

        # Get the current backend
        backend = registry.get_or_placeholder()
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

        # Clear preedit
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

        # TODO: Load custom PTT hotkey when implemented

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

        # Ensure audio capture is set up
        if not self._audio_capture.is_recording:
            if not self._audio_capture.setup(on_error=self._on_audio_error):
                LOG.error("Failed to set up audio capture")
                return False

        if not self._audio_capture.start():
            LOG.error("Failed to start audio capture")
            return False

        self._transition_to(EngineState.RECORDING)

        # Show recording indicator
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

        # Clear preedit
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

        # Show transcribing indicator
        self.update_preedit_text(
            IBus.Text.new_from_string("⏳ Transcribing..."),
            0,
            True,
        )

        # Submit to worker
        if self._worker:
            locale = self._settings.get_string("locale") or "en_US"
            self._worker.submit(segment, locale_hint=locale)
        else:
            LOG.warning("No worker available, using placeholder")
            # Placeholder: directly return to idle
            self._on_transcription_result(TranscriptResult(text="[No backend configured]"))

    def _on_transcription_result(self, result: TranscriptResult) -> None:
        """Handle transcription result (called in main loop)."""
        # Clear preedit
        self.update_preedit_text(
            IBus.Text.new_from_string(""),
            0,
            False,
        )

        if result.text:
            self._transition_to(EngineState.COMMITTING)
            self.commit_text(IBus.Text.new_from_string(result.text))
            LOG.info("Committed text: '%s'", result.text)

        self._transition_to(EngineState.IDLE)

    def _on_audio_error(self, error: str) -> None:
        """Handle audio capture error."""
        LOG.error("Audio error: %s", error)
        self._transition_to(EngineState.IDLE)

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

        # Check for push-to-talk hotkey
        if self._record_mode == RecordMode.PUSH_TO_TALK:
            if self._is_ptt_key(keyval, state):
                if is_release:
                    # Key released - stop recording
                    if self._state == EngineState.RECORDING:
                        self._stop_recording()
                        return True
                else:
                    # Key pressed - start recording
                    if self._state == EngineState.IDLE:
                        self._start_recording()
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

        # Register properties
        self.register_properties(self._prop_list)
        self._update_state_ui()

    def do_disable(self) -> None:
        """Called when the engine is disabled."""
        LOG.info("Engine disabled")

        # Stop any ongoing recording
        if self._state == EngineState.RECORDING:
            self._audio_capture.stop()

        self._transition_to(EngineState.IDLE)

    def do_focus_in(self) -> None:
        """Called when focus enters an input context."""
        LOG.debug("Focus in")
        self.register_properties(self._prop_list)
        self._update_state_ui()

    def do_focus_out(self) -> None:
        """Called when focus leaves an input context."""
        LOG.debug("Focus out")

        # Stop recording on focus loss
        if self._state == EngineState.RECORDING:
            self._audio_capture.stop()
            self._transition_to(EngineState.IDLE)

    def do_reset(self) -> None:
        """Called to reset the engine state."""
        LOG.debug("Reset")

        # Stop recording on reset
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
        super().__init__(
            connection=bus.get_connection(),
            object_path=IBus.PATH_FACTORY,
        )
        self._bus = bus
        self._engine_count = 0
        LOG.info("Engine factory created")

    def do_create_engine(self, engine_name: str) -> IBus.Engine | None:
        """Create a new engine instance.

        Args:
            engine_name: Name of the engine to create.

        Returns:
            New engine instance or None.
        """
        if engine_name != "speak2type":
            LOG.warning("Unknown engine name: %s", engine_name)
            return None

        self._engine_count += 1
        object_path = f"{IBus.PATH_ENGINE}/speak2type/{self._engine_count}"

        LOG.info("Creating engine: %s", object_path)
        return Speak2TypeEngine(self._bus, object_path)


def main() -> int:
    """Main entry point for the IBus engine."""
    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    LOG.info("speak2type engine starting")

    # Initialize IBus
    IBus.init()

    # Create bus connection
    bus = IBus.Bus()
    if not bus.is_connected():
        LOG.error("Cannot connect to IBus")
        return 1

    # Request name
    bus.request_name("org.freedesktop.IBus.speak2type", 0)

    # Create factory
    factory = Speak2TypeEngineFactory(bus)

    # Create component
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
