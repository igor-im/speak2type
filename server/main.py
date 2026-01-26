"""Reference HTTP server for speak2type.

A FastAPI server implementing both generic and OpenAI-compatible
transcription endpoints. Can be used for:

1. Testing the HTTP backend
2. Running speech models on a separate machine
3. Contract testing with OpenAPI schema

Usage:
    uvicorn server.main:app --port 8000

Endpoints:
    POST /transcribe              - Generic endpoint
    POST /v1/audio/transcriptions - OpenAI-compatible endpoint
"""

import io
import logging
import sys
import wave
from pathlib import Path
from typing import Annotated, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Add src to path for local backends
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

LOG = logging.getLogger(__name__)

app = FastAPI(
    title="speak2type Transcription Server",
    description="Reference HTTP server for speech-to-text transcription",
    version="0.1.0",
)


# Response models for OpenAPI schema
class TranscriptionSegment(BaseModel):
    """A segment of transcription with timing."""
    text: str
    start: float  # Start time in seconds
    end: float  # End time in seconds
    confidence: Optional[float] = None


class GenericTranscriptionResponse(BaseModel):
    """Response from generic /transcribe endpoint."""
    text: str
    segments: Optional[list[TranscriptionSegment]] = None
    language: Optional[str] = None


class OpenAITranscriptionResponse(BaseModel):
    """Response from OpenAI-compatible endpoint."""
    text: str


# Backend configuration
_backend = None
_backend_type = "placeholder"


def get_backend():
    """Get or initialize the transcription backend."""
    global _backend, _backend_type

    if _backend is not None:
        return _backend

    # Try to load a real backend
    try:
        from speak2type.backends import (
            VOSK_AVAILABLE,
            WHISPER_AVAILABLE,
            PARAKEET_AVAILABLE,
        )

        if PARAKEET_AVAILABLE:
            from speak2type.backends.parakeet_adapter import ParakeetBackend
            _backend = ParakeetBackend()
            if _backend.is_available:
                _backend_type = "parakeet"
                LOG.info("Using Parakeet backend")
                return _backend

        if WHISPER_AVAILABLE:
            from speak2type.backends.whisper_adapter import WhisperBackend
            _backend = WhisperBackend()
            if _backend.is_available:
                _backend_type = "whisper"
                LOG.info("Using Whisper backend")
                return _backend

        if VOSK_AVAILABLE:
            from speak2type.backends.vosk_adapter import VoskBackend
            _backend = VoskBackend()
            if _backend.is_available:
                _backend_type = "vosk"
                LOG.info("Using Vosk backend")
                return _backend

    except Exception as e:
        LOG.warning("Failed to load backend: %s", e)

    # Fall back to placeholder
    from speak2type.backends.base import PlaceholderBackend
    _backend = PlaceholderBackend()
    _backend_type = "placeholder"
    LOG.info("Using placeholder backend")
    return _backend


def read_audio_file(file: UploadFile) -> tuple[bytes, int]:
    """Read and decode audio from upload.

    Args:
        file: Uploaded file.

    Returns:
        Tuple of (pcm_bytes, sample_rate).
    """
    content = file.file.read()

    # Try to read as WAV
    try:
        wav_file = io.BytesIO(content)
        with wave.open(wav_file, "rb") as wav:
            sample_rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
            return frames, sample_rate
    except wave.Error:
        pass

    # Assume raw PCM at 16kHz
    LOG.warning("Could not read as WAV, assuming raw PCM at 16kHz")
    return content, 16000


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "ok",
        "backend": _backend_type,
        "version": "0.1.0",
    }


@app.post("/transcribe", response_model=GenericTranscriptionResponse)
async def transcribe_generic(
    audio: Annotated[UploadFile, File(description="Audio file to transcribe")],
    locale: Annotated[str, Form()] = "en_US",
):
    """Generic transcription endpoint.

    Accepts audio file via multipart form data and returns transcription.

    Args:
        audio: Audio file (WAV or raw PCM).
        locale: Locale hint (e.g., "en_US").

    Returns:
        Transcription result with text and optional segments.
    """
    backend = get_backend()

    try:
        pcm_bytes, sample_rate = read_audio_file(audio)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read audio: {e}")

    from speak2type.types import AudioSegment, AudioFormat

    segment = AudioSegment(
        pcm_bytes=pcm_bytes,
        format=AudioFormat(sample_rate=sample_rate),
    )

    result = backend.transcribe(segment, locale)

    # Convert to response model
    segments = None
    if result.segments:
        segments = [
            TranscriptionSegment(
                text=seg.text,
                start=seg.start_ms / 1000.0,
                end=seg.end_ms / 1000.0,
                confidence=seg.confidence,
            )
            for seg in result.segments
        ]

    return GenericTranscriptionResponse(
        text=result.text,
        segments=segments,
        language=result.language,
    )


@app.post("/v1/audio/transcriptions", response_model=OpenAITranscriptionResponse)
async def transcribe_openai(
    file: Annotated[UploadFile, File(description="Audio file to transcribe")],
    model: Annotated[str, Form()] = "whisper-1",
    language: Annotated[Optional[str], Form()] = None,
    response_format: Annotated[str, Form()] = "json",
):
    """OpenAI-compatible transcription endpoint.

    Implements the OpenAI Audio API transcription endpoint for compatibility
    with existing tools and libraries.

    Args:
        file: Audio file (WAV or raw PCM).
        model: Model name (ignored, uses configured backend).
        language: Language code (e.g., "en").
        response_format: Response format (only "json" supported).

    Returns:
        Transcription result with text.
    """
    if response_format != "json":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported response_format: {response_format}. Only 'json' is supported.",
        )

    backend = get_backend()

    try:
        pcm_bytes, sample_rate = read_audio_file(file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read audio: {e}")

    from speak2type.types import AudioSegment, AudioFormat

    segment = AudioSegment(
        pcm_bytes=pcm_bytes,
        format=AudioFormat(sample_rate=sample_rate),
    )

    # Convert language to locale
    locale = f"{language}_XX" if language else "en_US"

    result = backend.transcribe(segment, locale)

    return OpenAITranscriptionResponse(text=result.text)


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)
