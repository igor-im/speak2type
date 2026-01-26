"""pytest configuration and fixtures."""

import pytest


@pytest.fixture
def sample_audio_bytes() -> bytes:
    """Return sample PCM audio bytes (16kHz mono S16LE silence)."""
    # 1 second of silence at 16kHz, 16-bit mono = 32000 bytes
    return bytes(32000)


@pytest.fixture
def sample_audio_segment():
    """Return a sample AudioSegment for testing."""
    from speak2type.types import AudioSegment, AudioFormat

    return AudioSegment(
        pcm_bytes=bytes(32000),  # 1 second of silence
        format=AudioFormat(sample_rate=16000, channels=1, sample_fmt="s16le"),
    )
