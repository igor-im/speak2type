"""Audio capture using GStreamer pipeline."""

import logging
from typing import Callable

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
gi.require_version("GLib", "2.0")

from gi.repository import Gst, GstApp, GLib

from .types import AudioFormat, AudioSegment, AudioSource

LOG = logging.getLogger(__name__)

# Initialize GStreamer
Gst.init(None)


def _check_element_available(element_name: str) -> bool:
    """Check if a GStreamer element is available."""
    factory = Gst.ElementFactory.find(element_name)
    return factory is not None


def _get_audio_source_element() -> str:
    """Determine the best available audio source element.

    Prefers pulsesrc as pipewiresrc has permission issues on some systems.
    """
    # Prefer pulsesrc - it works reliably via pipewire-pulse
    if _check_element_available("pulsesrc"):
        LOG.info("Using pulsesrc (PulseAudio/PipeWire-pulse)")
        return "pulsesrc"
    elif _check_element_available("pipewiresrc"):
        LOG.info("Using pipewiresrc (native PipeWire)")
        return "pipewiresrc"
    else:
        LOG.error("No audio source available (pulsesrc or pipewiresrc)")
        raise RuntimeError("No audio source element available")


class AudioCapture:
    """Captures audio from microphone using GStreamer.

    Provides buffered audio capture for push-to-talk mode.
    """

    # Pipeline template with placeholder for source element
    _PIPELINE_TEMPLATE = (
        "{source} ! "
        "audioconvert ! "
        "audioresample ! "
        "audio/x-raw,format=S16LE,channels=1,rate=16000 ! "
        "appsink name=sink emit-signals=true sync=false"
    )

    # Alternative pipeline with webrtcdsp noise suppression
    _PIPELINE_TEMPLATE_WEBRTC = (
        "{source} ! "
        "audioconvert ! "
        "audioresample ! "
        "audio/x-raw,format=S16LE,channels=1,rate=16000 ! "
        "webrtcdsp noise-suppression-level=3 echo-cancel=false ! "
        "appsink name=sink emit-signals=true sync=false"
    )

    def __init__(
        self,
        audio_source: AudioSource = AudioSource.AUTO,
        use_noise_suppression: bool = False,  # Disabled for debugging
    ) -> None:
        """Initialize audio capture.

        Args:
            audio_source: Preferred audio source.
            use_noise_suppression: Whether to use webrtcdsp for noise suppression.
        """
        self._format = AudioFormat()
        self._audio_source = audio_source
        self._use_noise_suppression = use_noise_suppression

        self._pipeline: Gst.Pipeline | None = None
        self._appsink: Gst.Element | None = None
        self._bus: Gst.Bus | None = None

        self._buffer: bytearray = bytearray()
        self._is_recording = False

        self._on_error: Callable[[str], None] | None = None

    @property
    def format(self) -> AudioFormat:
        """Return the audio format."""
        return self._format

    @property
    def is_recording(self) -> bool:
        """Return whether audio capture is active."""
        return self._is_recording

    @property
    def is_setup(self) -> bool:
        """Return whether the pipeline is set up."""
        return self._pipeline is not None

    def _get_source_element(self) -> str:
        """Get the audio source element name based on preference."""
        if self._audio_source == AudioSource.PIPEWIRE:
            if _check_element_available("pipewiresrc"):
                return "pipewiresrc"
            LOG.warning("pipewiresrc requested but not available, falling back")

        if self._audio_source == AudioSource.PULSEAUDIO:
            if _check_element_available("pulsesrc"):
                return "pulsesrc"
            LOG.warning("pulsesrc requested but not available, falling back")

        return _get_audio_source_element()

    def _build_pipeline(self) -> str:
        """Build the pipeline description string."""
        source = self._get_source_element()

        # Check if webrtcdsp is available
        use_webrtc = self._use_noise_suppression and _check_element_available("webrtcdsp")

        if use_webrtc:
            LOG.debug("Using webrtcdsp for noise suppression")
            return self._PIPELINE_TEMPLATE_WEBRTC.format(source=source)
        else:
            LOG.debug("Not using noise suppression")
            return self._PIPELINE_TEMPLATE.format(source=source)

    def _on_new_sample(self, appsink: Gst.Element) -> Gst.FlowReturn:
        """Handle new audio sample from appsink (signal-based).

        IMPORTANT: Always pull samples to prevent pipeline backpressure.
        Only buffer them when actually recording.
        """
        sample = appsink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK

        buf = sample.get_buffer()
        success, map_info = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.OK

        # Always pull and unmap, but only buffer when recording
        if self._is_recording:
            self._buffer.extend(map_info.data)

        buf.unmap(map_info)
        return Gst.FlowReturn.OK

    def _on_bus_message(self, bus: Gst.Bus, message: Gst.Message) -> bool:
        """Handle GStreamer bus messages."""
        msg_type = message.type

        if msg_type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            LOG.error("GStreamer error: %s (%s)", error.message, debug)
            if self._on_error:
                self._on_error(error.message)

        elif msg_type == Gst.MessageType.WARNING:
            warning, debug = message.parse_warning()
            LOG.warning("GStreamer warning: %s (%s)", warning.message, debug)

        elif msg_type == Gst.MessageType.STATE_CHANGED:
            if message.src == self._pipeline:
                old, new, pending = message.parse_state_changed()
                LOG.debug("Pipeline state: %s -> %s", old.value_nick, new.value_nick)

        return True

    def _create_pipeline(self) -> bool:
        """Create and configure the GStreamer pipeline.

        Returns:
            True if pipeline was created successfully.
        """
        try:
            pipeline_desc = self._build_pipeline()
            LOG.info("Creating pipeline: %s", pipeline_desc)

            self._pipeline = Gst.parse_launch(pipeline_desc)
            if self._pipeline is None:
                LOG.error("Failed to create pipeline")
                return False

            self._appsink = self._pipeline.get_by_name("sink")
            if self._appsink is None:
                LOG.error("Failed to get appsink element")
                return False

            # Configure appsink for callback-based sample retrieval
            # Always drain (via callback) to prevent pipeline backpressure
            self._appsink.set_property("emit-signals", True)
            self._appsink.set_property("sync", False)
            self._appsink.set_property("drop", True)  # Drop old buffers if we fall behind
            self._appsink.set_property("max-buffers", 5)  # Small queue
            self._appsink.connect("new-sample", self._on_new_sample)

            # Set up bus for messages
            self._bus = self._pipeline.get_bus()
            self._bus.add_signal_watch()
            self._bus.connect("message", self._on_bus_message)

            # Start pipeline in PLAYING state - keep it running to avoid hangs
            ret = self._pipeline.set_state(Gst.State.PLAYING)
            if ret == Gst.StateChangeReturn.FAILURE:
                LOG.error("Failed to start pipeline")
                return False

            LOG.info("Audio capture pipeline ready and running")
            return True

        except Exception as e:
            LOG.exception("Failed to create pipeline: %s", e)
            return False

    def setup(self, on_error: Callable[[str], None] | None = None) -> bool:
        """Set up the GStreamer pipeline.

        Args:
            on_error: Callback for error notifications.

        Returns:
            True if setup succeeded.
        """
        self._on_error = on_error
        return self._create_pipeline()

    def start(self) -> bool:
        """Start recording audio.

        Returns:
            True if started successfully.
        """
        if self._pipeline is None:
            LOG.error("Pipeline not set up")
            return False

        if self._is_recording:
            LOG.warning("Already recording")
            return True

        # Clear buffer - stale samples are continuously discarded by the callback
        self._buffer.clear()

        # Pipeline should already be PLAYING from setup, but ensure it
        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            LOG.error("Failed to start pipeline")
            return False

        self._is_recording = True
        LOG.info("Started recording")
        return True

    def stop(self) -> AudioSegment | None:
        """Stop recording and return captured audio.

        Returns:
            AudioSegment with captured audio, or None if no audio.
        """
        if self._pipeline is None:
            LOG.error("Pipeline not set up")
            return None

        if not self._is_recording:
            LOG.warning("Not recording")
            return None

        self._is_recording = False
        # Pipeline stays PLAYING - callback continues to drain samples
        # but discards them since _is_recording is False

        # Get captured audio
        if len(self._buffer) == 0:
            LOG.warning("No audio captured")
            return None

        segment = AudioSegment(
            pcm_bytes=bytes(self._buffer),
            format=self._format,
        )

        LOG.info("Captured %.2f seconds of audio", segment.duration_seconds)

        # Clear buffer for next recording
        self._buffer.clear()

        return segment

    def destroy(self) -> None:
        """Clean up resources."""
        if self._bus:
            self._bus.remove_signal_watch()
            self._bus = None

        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None

        self._appsink = None
        LOG.info("Audio capture destroyed")
