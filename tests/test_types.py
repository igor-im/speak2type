"""Tests for speak2type types."""

import pytest

from speak2type.types import (
    AudioFormat,
    AudioSegment,
    EngineState,
    RecordMode,
    TranscriptResult,
)


class TestAudioFormat:
    """Tests for AudioFormat."""

    def test_default_values(self):
        """Test default audio format values."""
        fmt = AudioFormat()
        assert fmt.sample_rate == 16000
        assert fmt.channels == 1
        assert fmt.sample_fmt == "s16le"

    def test_bytes_per_sample(self):
        """Test bytes per sample calculation."""
        fmt = AudioFormat()
        assert fmt.bytes_per_sample == 2  # s16le = 2 bytes

        fmt_f32 = AudioFormat(sample_fmt="f32le")
        assert fmt_f32.bytes_per_sample == 4

    def test_bytes_per_second(self):
        """Test bytes per second calculation."""
        fmt = AudioFormat()
        # 16000 samples/sec * 1 channel * 2 bytes = 32000 bytes/sec
        assert fmt.bytes_per_second == 32000

        fmt_stereo = AudioFormat(channels=2)
        assert fmt_stereo.bytes_per_second == 64000


class TestAudioSegment:
    """Tests for AudioSegment."""

    def test_duration_calculation(self, sample_audio_bytes):
        """Test duration calculation from PCM bytes."""
        segment = AudioSegment(pcm_bytes=sample_audio_bytes)
        # 32000 bytes / 32000 bytes per second = 1 second = 1000 ms
        assert segment.duration_ms == 1000
        assert segment.duration_seconds == 1.0

    def test_empty_segment(self):
        """Test empty audio segment."""
        segment = AudioSegment(pcm_bytes=b"")
        assert segment.duration_ms == 0
        assert segment.duration_seconds == 0.0

    def test_custom_format(self):
        """Test segment with custom format."""
        fmt = AudioFormat(sample_rate=8000, channels=1, sample_fmt="s16le")
        segment = AudioSegment(pcm_bytes=bytes(16000), format=fmt)
        # 16000 bytes / (8000 * 1 * 2) = 1 second
        assert segment.duration_seconds == 1.0


class TestEngineState:
    """Tests for EngineState enum."""

    def test_all_states_exist(self):
        """Test that all required states exist."""
        assert EngineState.IDLE
        assert EngineState.RECORDING
        assert EngineState.TRANSCRIBING
        assert EngineState.COMMITTING

    def test_states_are_unique(self):
        """Test that states have unique values."""
        values = [s.value for s in EngineState]
        assert len(values) == len(set(values))


class TestRecordMode:
    """Tests for RecordMode enum."""

    def test_modes_exist(self):
        """Test that recording modes exist."""
        assert RecordMode.TOGGLE.value == "toggle"
        assert RecordMode.PUSH_TO_TALK.value == "push_to_talk"


class TestTranscriptResult:
    """Tests for TranscriptResult."""

    def test_minimal_result(self):
        """Test creating minimal result."""
        result = TranscriptResult(text="hello")
        assert result.text == "hello"
        assert result.segments is None
        assert result.language is None
        assert result.confidence is None
        assert result.is_partial is False

    def test_full_result(self):
        """Test creating full result with all fields."""
        from speak2type.types import Segment

        segments = [Segment(text="hello", start_ms=0, end_ms=500)]
        result = TranscriptResult(
            text="hello",
            segments=segments,
            language="en",
            confidence=0.95,
            is_partial=False,
        )
        assert result.text == "hello"
        assert len(result.segments) == 1
        assert result.language == "en"
        assert result.confidence == 0.95
