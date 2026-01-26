"""Core types for speak2type."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Protocol, Iterator, Callable


class EngineState(Enum):
    """State machine states for the speech-to-text engine."""
    IDLE = auto()
    RECORDING = auto()
    TRANSCRIBING = auto()
    COMMITTING = auto()


class RecordMode(Enum):
    """Recording activation mode."""
    TOGGLE = "toggle"
    PUSH_TO_TALK = "push_to_talk"


class AudioSource(Enum):
    """Audio source preference."""
    AUTO = "auto"
    PIPEWIRE = "pipewire"
    PULSEAUDIO = "pulseaudio"


@dataclass(frozen=True)
class AudioFormat:
    """Audio format specification."""
    sample_rate: int = 16000
    channels: int = 1
    sample_fmt: str = "s16le"

    @property
    def bytes_per_sample(self) -> int:
        """Return bytes per sample based on format."""
        fmt_sizes = {"s16le": 2, "f32le": 4, "s32le": 4}
        return fmt_sizes.get(self.sample_fmt, 2)

    @property
    def bytes_per_second(self) -> int:
        """Return bytes per second of audio."""
        return self.sample_rate * self.channels * self.bytes_per_sample


@dataclass
class AudioSegment:
    """A segment of audio data."""
    pcm_bytes: bytes
    format: AudioFormat = field(default_factory=AudioFormat)

    @property
    def duration_ms(self) -> int:
        """Return duration in milliseconds."""
        if self.format.bytes_per_second == 0:
            return 0
        return int(len(self.pcm_bytes) * 1000 / self.format.bytes_per_second)

    @property
    def duration_seconds(self) -> float:
        """Return duration in seconds."""
        return self.duration_ms / 1000.0


@dataclass
class Segment:
    """A transcription segment with timing."""
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None


@dataclass
class TranscriptResult:
    """Result of speech transcription."""
    text: str
    segments: list[Segment] | None = None
    language: str | None = None
    confidence: float | None = None
    is_partial: bool = False


class Backend(Protocol):
    """Protocol for speech recognition backends."""

    @property
    def id(self) -> str:
        """Unique identifier for this backend."""
        ...

    @property
    def name(self) -> str:
        """Human-readable name for this backend."""
        ...

    def transcribe(
        self,
        segment: AudioSegment,
        locale_hint: str,
        options: dict | None = None,
    ) -> TranscriptResult:
        """Transcribe an audio segment to text.

        Args:
            segment: Audio data to transcribe.
            locale_hint: Suggested locale (e.g., "en_US").
            options: Backend-specific options.

        Returns:
            Transcription result.
        """
        ...


class StreamingBackend(Backend, Protocol):
    """Protocol for streaming speech recognition backends."""

    def stream(
        self,
        frames_iter: Iterator[bytes],
        on_partial: Callable[[str], None],
        on_final: Callable[[TranscriptResult], None],
    ) -> None:
        """Stream audio frames for real-time transcription.

        Args:
            frames_iter: Iterator yielding audio frames.
            on_partial: Callback for partial transcription results.
            on_final: Callback for final transcription result.
        """
        ...
