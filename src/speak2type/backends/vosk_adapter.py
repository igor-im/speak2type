"""Vosk speech recognition backend adapter.

This adapter uses the Vosk library for offline speech recognition.
It requires the vosk Python package and downloaded models.
"""

import json
import logging
import os
from pathlib import Path

from ..types import AudioSegment, TranscriptResult, Segment

LOG = logging.getLogger(__name__)

# Check if vosk is available
try:
    from vosk import Model, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False
    LOG.warning("vosk package not available. Install with: pip install vosk")


def get_xdg_data_home() -> Path:
    """Get XDG_DATA_HOME directory."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def get_model_dir() -> Path:
    """Get the default model directory for Vosk."""
    return get_xdg_data_home() / "speak2type" / "models" / "vosk"


class VoskBackend:
    """Vosk speech recognition backend for batch transcription.

    Uses the Vosk library to transcribe pre-recorded audio segments.
    This is suitable for push-to-talk mode where audio is captured
    first and then transcribed.
    """

    def __init__(self, model_path: str | Path | None = None) -> None:
        """Initialize the Vosk backend.

        Args:
            model_path: Path to Vosk model directory. If None, will search
                        default locations.
        """
        self._model: "Model | None" = None
        self._model_path: Path | None = None

        if not VOSK_AVAILABLE:
            LOG.error("Vosk not available")
            return

        if model_path:
            self._load_model(Path(model_path))
        else:
            self._find_and_load_model()

    @property
    def id(self) -> str:
        return "vosk"

    @property
    def name(self) -> str:
        return "Vosk (Offline)"

    @property
    def is_available(self) -> bool:
        """Check if Vosk is available and model is loaded."""
        return VOSK_AVAILABLE and self._model is not None

    def _find_and_load_model(self) -> None:
        """Find and load a Vosk model from default locations."""
        search_paths = [
            get_model_dir(),
            Path.home() / ".vosk",
            Path("/usr/share/vosk"),
            Path("/usr/local/share/vosk"),
        ]

        for base_path in search_paths:
            if not base_path.exists():
                continue

            # Look for model directories (they contain 'am' subdirectory)
            for item in base_path.iterdir():
                if item.is_dir() and (item / "am").exists():
                    LOG.debug("Found potential model: %s", item)
                    if self._load_model(item):
                        return

            # Also check if base_path itself is a model
            if (base_path / "am").exists():
                if self._load_model(base_path):
                    return

        LOG.warning("No Vosk model found in default locations")

    def _load_model(self, model_path: Path) -> bool:
        """Load a Vosk model from the given path.

        Args:
            model_path: Path to model directory.

        Returns:
            True if model loaded successfully.
        """
        if not VOSK_AVAILABLE:
            return False

        if not model_path.exists():
            LOG.error("Model path does not exist: %s", model_path)
            return False

        try:
            LOG.info("Loading Vosk model from: %s", model_path)
            self._model = Model(str(model_path))
            self._model_path = model_path
            LOG.info("Vosk model loaded successfully")
            return True
        except Exception as e:
            LOG.error("Failed to load Vosk model: %s", e)
            self._model = None
            return False

    def transcribe(
        self,
        segment: AudioSegment,
        locale_hint: str,
        options: dict | None = None,
    ) -> TranscriptResult:
        """Transcribe an audio segment using Vosk.

        Args:
            segment: Audio segment to transcribe.
            locale_hint: Locale hint (not used by Vosk after model selection).
            options: Additional options (not used).

        Returns:
            Transcription result.
        """
        if not self.is_available:
            return TranscriptResult(
                text="[Vosk not available - install vosk package and download model]",
                confidence=0.0,
            )

        try:
            # Create recognizer with the loaded model
            rec = KaldiRecognizer(self._model, segment.format.sample_rate)
            rec.SetWords(True)  # Get word-level timing

            # Feed audio data
            audio_bytes = segment.pcm_bytes
            chunk_size = 4000  # Process in chunks

            for i in range(0, len(audio_bytes), chunk_size):
                chunk = audio_bytes[i:i + chunk_size]
                rec.AcceptWaveform(chunk)

            # Get final result
            result_json = rec.FinalResult()
            result = json.loads(result_json)

            text = result.get("text", "")

            # Extract word-level segments if available
            segments = None
            if "result" in result:
                segments = [
                    Segment(
                        text=word["word"],
                        start_ms=int(word["start"] * 1000),
                        end_ms=int(word["end"] * 1000),
                        confidence=word.get("conf"),
                    )
                    for word in result["result"]
                ]

            LOG.debug("Vosk transcription: '%s'", text)

            return TranscriptResult(
                text=text,
                segments=segments,
                confidence=None,  # Vosk doesn't provide overall confidence
            )

        except Exception as e:
            LOG.exception("Vosk transcription error: %s", e)
            return TranscriptResult(
                text=f"[Transcription error: {e}]",
                confidence=0.0,
            )

    def set_model(self, model_path: str | Path) -> bool:
        """Set a new model.

        Args:
            model_path: Path to model directory.

        Returns:
            True if model loaded successfully.
        """
        return self._load_model(Path(model_path))
