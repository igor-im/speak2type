"""HTTP speech recognition backend adapter.

This adapter connects to remote speech-to-text services via HTTP.
Supports two dialects:

1. Generic: POST /transcribe with multipart form data
2. OpenAI-compatible: POST /v1/audio/transcriptions (works with Whisper API, etc.)

This enables:
- Connection to cloud speech services
- Using GPU servers for transcription
- Running heavy models on separate machines
"""

import io
import logging
from dataclasses import dataclass
from enum import Enum
from typing import BinaryIO
from urllib.parse import urlparse

from ..types import AudioSegment, TranscriptResult, Segment

LOG = logging.getLogger(__name__)

# Check if httpx is available
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    LOG.warning("httpx not available. Install with: pip install httpx")


class HttpDialect(Enum):
    """HTTP API dialect."""
    GENERIC = "generic"
    OPENAI = "openai"


@dataclass
class HttpBackendConfig:
    """Configuration for HTTP backend."""

    endpoint_url: str  # Base URL (e.g., "http://localhost:8000")
    dialect: HttpDialect = HttpDialect.GENERIC
    auth_header: str | None = None  # Bearer token or API key
    timeout_s: float = 30.0
    model: str | None = None  # Model name for OpenAI dialect
    response_format: str = "json"  # Response format for OpenAI


class HttpBackend:
    """HTTP speech recognition backend.

    Connects to remote speech-to-text services via HTTP API.
    Supports both generic and OpenAI-compatible endpoints.
    """

    def __init__(
        self,
        endpoint_url: str | None = None,
        dialect: HttpDialect | str = HttpDialect.GENERIC,
        auth_header: str | None = None,
        timeout_s: float = 30.0,
        model: str | None = None,
    ) -> None:
        """Initialize the HTTP backend.

        Args:
            endpoint_url: Base URL of the transcription service.
            dialect: API dialect (generic or openai).
            auth_header: Authorization header value (e.g., "Bearer sk-xxx").
            timeout_s: Request timeout in seconds.
            model: Model name for OpenAI dialect.
        """
        # Validate endpoint URL
        if endpoint_url is not None:
            parsed = urlparse(endpoint_url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError(
                    f"Invalid endpoint URL scheme: {parsed.scheme!r}. "
                    "Must be 'http' or 'https'."
                )
            if not parsed.netloc:
                raise ValueError(f"Invalid endpoint URL: missing host in {endpoint_url!r}")

            # Security: require HTTPS when auth is provided (unless localhost)
            is_localhost = parsed.hostname in ("localhost", "127.0.0.1", "::1")
            if auth_header and parsed.scheme != "https" and not is_localhost:
                raise ValueError(
                    "HTTPS required when using authentication with remote endpoints. "
                    f"Got: {endpoint_url}"
                )

        self._endpoint_url = endpoint_url
        self._dialect = HttpDialect(dialect) if isinstance(dialect, str) else dialect
        self._auth_header = auth_header
        self._timeout_s = timeout_s
        self._model = model
        self._client: "httpx.Client | None" = None

        if not HTTPX_AVAILABLE:
            LOG.error("httpx not available")

    @property
    def id(self) -> str:
        return "http"

    @property
    def name(self) -> str:
        return f"HTTP ({self._dialect.value})"

    @property
    def is_available(self) -> bool:
        """Check if HTTP backend is available."""
        return HTTPX_AVAILABLE and self._endpoint_url is not None

    @property
    def endpoint_url(self) -> str | None:
        """Get the configured endpoint URL."""
        return self._endpoint_url

    @endpoint_url.setter
    def endpoint_url(self, value: str | None) -> None:
        """Set the endpoint URL."""
        self._endpoint_url = value
        # Close existing client to force reconnection
        if self._client:
            self._client.close()
            self._client = None

    def _get_client(self) -> "httpx.Client":
        """Get or create HTTP client."""
        if self._client is None:
            headers = {}
            if self._auth_header:
                headers["Authorization"] = self._auth_header

            self._client = httpx.Client(
                timeout=self._timeout_s,
                headers=headers,
            )

        return self._client

    def _transcribe_generic(
        self,
        audio_file: BinaryIO,
        locale_hint: str,
        options: dict | None = None,
    ) -> TranscriptResult:
        """Transcribe using generic dialect.

        POST /transcribe
        Content-Type: multipart/form-data
        Body: audio file

        Expected response:
        {
            "text": "...",
            "segments": [...] (optional)
        }
        """
        client = self._get_client()
        url = f"{self._endpoint_url.rstrip('/')}/transcribe"

        files = {"audio": ("audio.wav", audio_file, "audio/wav")}
        data = {"locale": locale_hint}

        if options:
            data.update(options)

        LOG.debug("POST %s", url)

        try:
            response = client.post(url, files=files, data=data)
            response.raise_for_status()

            result = response.json()
            text = result.get("text", "")

            # Parse segments if available
            segments = None
            if "segments" in result:
                segments = [
                    Segment(
                        text=seg.get("text", ""),
                        start_ms=int(seg.get("start", 0) * 1000),
                        end_ms=int(seg.get("end", 0) * 1000),
                        confidence=seg.get("confidence"),
                    )
                    for seg in result["segments"]
                ]

            return TranscriptResult(
                text=text,
                segments=segments,
                language=result.get("language"),
            )

        except httpx.HTTPStatusError as e:
            LOG.error("HTTP error: %s", e)
            return TranscriptResult(
                text=f"[HTTP error: {e.response.status_code}]",
                confidence=0.0,
            )
        except httpx.TimeoutException:
            LOG.error("Request timed out")
            return TranscriptResult(
                text="[Request timed out]",
                confidence=0.0,
            )
        except Exception as e:
            LOG.exception("HTTP request failed: %s", e)
            return TranscriptResult(
                text=f"[Request failed: {e}]",
                confidence=0.0,
            )

    def _transcribe_openai(
        self,
        audio_file: BinaryIO,
        locale_hint: str,
        options: dict | None = None,
    ) -> TranscriptResult:
        """Transcribe using OpenAI-compatible dialect.

        POST /v1/audio/transcriptions
        Content-Type: multipart/form-data
        Body: file, model, language (optional)

        Expected response:
        {
            "text": "..."
        }
        """
        client = self._get_client()
        url = f"{self._endpoint_url.rstrip('/')}/v1/audio/transcriptions"

        files = {"file": ("audio.wav", audio_file, "audio/wav")}
        data = {
            "model": self._model or "whisper-1",
            "response_format": "json",
        }

        # Add language hint if provided (2-letter code)
        if locale_hint:
            data["language"] = locale_hint[:2].lower()

        if options:
            data.update(options)

        LOG.debug("POST %s (OpenAI dialect)", url)

        try:
            response = client.post(url, files=files, data=data)
            response.raise_for_status()

            result = response.json()
            text = result.get("text", "")

            return TranscriptResult(
                text=text,
                language=locale_hint[:2] if locale_hint else None,
            )

        except httpx.HTTPStatusError as e:
            LOG.error("HTTP error: %s", e)
            return TranscriptResult(
                text=f"[HTTP error: {e.response.status_code}]",
                confidence=0.0,
            )
        except httpx.TimeoutException:
            LOG.error("Request timed out")
            return TranscriptResult(
                text="[Request timed out]",
                confidence=0.0,
            )
        except Exception as e:
            LOG.exception("HTTP request failed: %s", e)
            return TranscriptResult(
                text=f"[Request failed: {e}]",
                confidence=0.0,
            )

    def transcribe(
        self,
        segment: AudioSegment,
        locale_hint: str,
        options: dict | None = None,
    ) -> TranscriptResult:
        """Transcribe an audio segment via HTTP.

        Args:
            segment: Audio segment to transcribe.
            locale_hint: Locale hint (e.g., "en_US").
            options: Additional options.

        Returns:
            Transcription result.
        """
        if not self.is_available:
            return TranscriptResult(
                text="[HTTP backend not configured - set endpoint URL]",
                confidence=0.0,
            )

        # Create WAV file in memory
        audio_file = self._create_wav_file(segment)

        try:
            if self._dialect == HttpDialect.OPENAI:
                return self._transcribe_openai(audio_file, locale_hint, options)
            else:
                return self._transcribe_generic(audio_file, locale_hint, options)
        finally:
            audio_file.close()

    def _create_wav_file(self, segment: AudioSegment) -> io.BytesIO:
        """Create a WAV file from audio segment.

        Args:
            segment: Audio segment.

        Returns:
            BytesIO with WAV data.
        """
        import struct

        # WAV file header
        pcm_data = segment.pcm_bytes
        sample_rate = segment.format.sample_rate
        channels = segment.format.channels
        bits_per_sample = 16  # S16LE

        # Calculate sizes
        data_size = len(pcm_data)
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8

        # Build WAV header
        wav_header = struct.pack(
            "<4sI4s"  # RIFF header
            "4sIHHIIHH"  # fmt chunk
            "4sI",  # data chunk header
            b"RIFF",
            36 + data_size,  # file size - 8
            b"WAVE",
            b"fmt ",
            16,  # fmt chunk size
            1,  # audio format (PCM)
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            data_size,
        )

        # Create file in memory
        wav_file = io.BytesIO()
        wav_file.write(wav_header)
        wav_file.write(pcm_data)
        wav_file.seek(0)

        return wav_file

    def configure(
        self,
        endpoint_url: str | None = None,
        dialect: HttpDialect | str | None = None,
        auth_header: str | None = None,
        timeout_s: float | None = None,
        model: str | None = None,
    ) -> None:
        """Update backend configuration.

        Args:
            endpoint_url: Base URL of the transcription service.
            dialect: API dialect.
            auth_header: Authorization header value.
            timeout_s: Request timeout in seconds.
            model: Model name for OpenAI dialect.
        """
        if endpoint_url is not None:
            self._endpoint_url = endpoint_url

        if dialect is not None:
            self._dialect = HttpDialect(dialect) if isinstance(dialect, str) else dialect

        if auth_header is not None:
            self._auth_header = auth_header

        if timeout_s is not None:
            self._timeout_s = timeout_s

        if model is not None:
            self._model = model

        # Close existing client to apply new settings
        if self._client:
            self._client.close()
            self._client = None

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
