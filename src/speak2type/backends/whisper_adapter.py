"""Whisper speech recognition backend adapter.

This adapter uses pywhispercpp (whisper.cpp Python bindings) for
offline speech recognition. It provides high-quality transcription
with optional GPU acceleration.
"""

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ..types import AudioSegment, TranscriptResult, Segment

if TYPE_CHECKING:
    from pywhispercpp.model import Model as WhisperModel

LOG = logging.getLogger(__name__)

# Pattern to filter out non-speech segments like [music], (applause), etc.
SPECIAL_PATTERN = re.compile(r"^(?:\[[^\]]+\]|\([^)]+\))$", re.IGNORECASE)

# Check if pywhispercpp is available
try:
    from pywhispercpp.model import Model
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    LOG.warning("pywhispercpp not available. Install with: pip install pywhispercpp")


def get_xdg_data_home() -> Path:
    """Get XDG_DATA_HOME directory."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def get_model_dir() -> Path:
    """Get the default model directory for Whisper."""
    return get_xdg_data_home() / "speak2type" / "models" / "whisper"


class WhisperBackend:
    """Whisper speech recognition backend using whisper.cpp.

    Uses pywhispercpp for high-quality offline transcription.
    Supports multiple model sizes (tiny, base, small, medium, large).
    """

    # Model size recommendations
    MODEL_SIZES = {
        "tiny": "Fastest, lowest quality (~75MB)",
        "base": "Good balance (~150MB)",
        "small": "Higher quality (~500MB)",
        "medium": "High quality (~1.5GB)",
        "large": "Best quality (~3GB)",
    }

    def __init__(
        self,
        model_path: str | Path | None = None,
        language: str | None = None,
        n_threads: int = 4,
    ) -> None:
        """Initialize the Whisper backend.

        Args:
            model_path: Path to Whisper model file (.bin). If None, will search
                        default locations.
            language: Language code (e.g., 'en') or None for auto-detect.
            n_threads: Number of threads for inference.
        """
        self._model: "WhisperModel | None" = None
        self._model_path: Path | None = None
        self._language = language
        self._n_threads = n_threads

        if not WHISPER_AVAILABLE:
            LOG.error("Whisper not available")
            return

        if model_path:
            self._load_model(Path(model_path))
        else:
            self._find_and_load_model()

    @property
    def id(self) -> str:
        return "whisper"

    @property
    def name(self) -> str:
        return "Whisper.cpp (Offline)"

    @property
    def is_available(self) -> bool:
        """Check if Whisper is available and model is loaded."""
        return WHISPER_AVAILABLE and self._model is not None

    def _find_and_load_model(self) -> None:
        """Find and load a Whisper model from default locations."""
        search_paths = [
            get_model_dir(),
            Path.home() / ".cache" / "whisper",
            Path("/usr/share/whisper"),
            Path("/usr/local/share/whisper"),
        ]

        # Look for model files (.bin)
        for base_path in search_paths:
            if not base_path.exists():
                continue

            for item in base_path.iterdir():
                if item.is_file() and item.suffix == ".bin":
                    LOG.debug("Found potential model: %s", item)
                    if self._load_model(item):
                        return

        LOG.warning("No Whisper model found in default locations")

    def _load_model(self, model_path: Path) -> bool:
        """Load a Whisper model from the given path.

        Args:
            model_path: Path to model file.

        Returns:
            True if model loaded successfully.
        """
        if not WHISPER_AVAILABLE:
            return False

        if not model_path.exists():
            LOG.error("Model path does not exist: %s", model_path)
            return False

        try:
            LOG.info("Loading Whisper model from: %s", model_path)

            kwargs = {
                "n_threads": self._n_threads,
                "print_realtime": False,
                "print_progress": False,
            }

            if self._language:
                kwargs["language"] = self._language

            self._model = Model(str(model_path), **kwargs)
            self._model_path = model_path
            LOG.info("Whisper model loaded successfully")
            return True

        except Exception as e:
            LOG.error("Failed to load Whisper model: %s", e)
            self._model = None
            return False

    def transcribe(
        self,
        segment: AudioSegment,
        locale_hint: str,
        options: dict | None = None,
    ) -> TranscriptResult:
        """Transcribe an audio segment using Whisper.

        Args:
            segment: Audio segment to transcribe.
            locale_hint: Locale hint (used to set language if not already set).
            options: Additional options.

        Returns:
            Transcription result.
        """
        if not self.is_available:
            return TranscriptResult(
                text="[Whisper not available - install pywhispercpp and download model]",
                confidence=0.0,
            )

        try:
            # Convert PCM bytes to float32 numpy array
            audio_int16 = np.frombuffer(segment.pcm_bytes, dtype=np.int16)
            audio_float = audio_int16.astype(np.float32) / 32768.0

            LOG.debug(
                "Transcribing %d samples (%.2f seconds)",
                len(audio_float),
                len(audio_float) / segment.format.sample_rate,
            )

            # Transcribe
            segments_result = self._model.transcribe(audio_float)

            # Process segments
            text_parts = []
            segments_list = []

            for seg in segments_result:
                if not hasattr(seg, "text"):
                    continue

                seg_text = seg.text.strip()

                # Filter out special markers like [music], (applause)
                if SPECIAL_PATTERN.match(seg_text):
                    LOG.debug("Filtered special segment: '%s'", seg_text)
                    continue

                if seg_text:
                    text_parts.append(seg_text)

                    # Create segment with timing if available
                    segment_obj = Segment(
                        text=seg_text,
                        start_ms=int(getattr(seg, "t0", 0) * 10),  # Convert to ms
                        end_ms=int(getattr(seg, "t1", 0) * 10),
                    )
                    segments_list.append(segment_obj)

            text = " ".join(text_parts).strip()

            LOG.info("Whisper transcription: '%s'", text)

            return TranscriptResult(
                text=text,
                segments=segments_list if segments_list else None,
                language=self._language,
            )

        except Exception as e:
            LOG.exception("Whisper transcription error: %s", e)
            return TranscriptResult(
                text=f"[Transcription error: {e}]",
                confidence=0.0,
            )

    def set_model(self, model_path: str | Path) -> bool:
        """Set a new model.

        Args:
            model_path: Path to model file.

        Returns:
            True if model loaded successfully.
        """
        return self._load_model(Path(model_path))

    def set_language(self, language: str | None) -> None:
        """Set the transcription language.

        Args:
            language: Language code (e.g., 'en') or None for auto-detect.
        """
        self._language = language
        # Reload model with new language if already loaded
        if self._model_path:
            self._load_model(self._model_path)
