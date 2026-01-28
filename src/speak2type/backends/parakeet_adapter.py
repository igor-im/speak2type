"""Parakeet ONNX speech recognition backend adapter.

This adapter uses the onnx-asr library to run NVIDIA Parakeet TDT models
for high-performance offline speech recognition.

Parakeet models are known for:
- Fast inference (high RTFx)
- Good accuracy
- CPU-friendly with optional CUDA acceleration
"""

import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from ..types import AudioSegment, TranscriptResult, Segment

LOG = logging.getLogger(__name__)

# Check if onnx-asr is available
try:
    import onnx_asr
    import onnxruntime
    PARAKEET_AVAILABLE = True
except ImportError:
    PARAKEET_AVAILABLE = False
    LOG.warning("onnx-asr not available. Install with: pip install onnx-asr")


# Model name mapping for onnx-asr
MODEL_NAMES = {
    "parakeet-v2": "nemo-parakeet-tdt-0.6b-v2",
    "parakeet-v3": "nemo-parakeet-tdt-0.6b-v3",  # multilingual
    "whisper-base": "whisper-base",
}


class ParakeetBackend:
    """Parakeet ONNX speech recognition backend.

    Uses onnx-asr to run NVIDIA Parakeet TDT models for high-performance
    transcription with CPU or CUDA acceleration.

    Supported models:
    - nemo-parakeet-tdt-0.6b-v2 (English)
    - nemo-parakeet-tdt-0.6b-v3 (Multilingual)
    """

    DEFAULT_MODEL = "nemo-parakeet-tdt-0.6b-v2"  # English-only (v3 is multilingual)

    def __init__(
        self,
        model_name: str | None = None,
        use_cuda: bool = False,
        num_threads: int = 4,
    ) -> None:
        """Initialize the Parakeet backend.

        Args:
            model_name: Model name for onnx-asr (e.g., "nemo-parakeet-tdt-0.6b-v2").
            use_cuda: Whether to use CUDA for inference.
            num_threads: Number of threads for CPU inference.
        """
        self._model: Any = None
        self._model_name = model_name or self.DEFAULT_MODEL
        self._use_cuda = use_cuda
        self._num_threads = num_threads

        if not PARAKEET_AVAILABLE:
            LOG.error("Parakeet not available")
            return

        self._load_model()

    @property
    def id(self) -> str:
        return "parakeet"

    @property
    def name(self) -> str:
        return f"Parakeet TDT ({self._model_name})"

    @property
    def is_available(self) -> bool:
        """Check if Parakeet is available and model is loaded."""
        return PARAKEET_AVAILABLE and self._model is not None

    def _get_providers(self) -> list[str]:
        """Get execution providers based on configuration."""
        if self._use_cuda:
            providers = onnxruntime.get_available_providers()
            if "CUDAExecutionProvider" in providers:
                return ["CUDAExecutionProvider", "CPUExecutionProvider"]
            LOG.warning("CUDA requested but not available, falling back to CPU")

        return ["CPUExecutionProvider"]

    def _load_model(self) -> bool:
        """Load model using onnx-asr.

        Returns:
            True if model loaded successfully.
        """
        if not PARAKEET_AVAILABLE:
            return False

        try:
            LOG.info("Loading Parakeet model: %s", self._model_name)

            # Create session options
            sess_options = onnxruntime.SessionOptions()
            sess_options.intra_op_num_threads = self._num_threads
            sess_options.inter_op_num_threads = self._num_threads

            # Load using new onnx-asr API
            self._model = onnx_asr.load_model(
                self._model_name,
                sess_options=sess_options,
                providers=self._get_providers(),
            )

            LOG.info("Parakeet model loaded successfully")
            return True

        except Exception as e:
            LOG.error("Failed to load Parakeet model: %s", e)
            self._model = None
            return False

    def transcribe(
        self,
        segment: AudioSegment,
        locale_hint: str,
        options: dict | None = None,
    ) -> TranscriptResult:
        """Transcribe an audio segment using Parakeet.

        Args:
            segment: Audio segment to transcribe.
            locale_hint: Locale hint (used for model selection if multilingual).
            options: Additional options.

        Returns:
            Transcription result.
        """
        if not self.is_available:
            return TranscriptResult(
                text="[Parakeet not available - install onnx-asr and download model]",
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

            # Transcribe using onnx-asr recognize() method
            text = self._model.recognize(audio_float, sample_rate=segment.format.sample_rate)
            text = text.strip() if text else ""

            LOG.debug("Parakeet transcription: '%s'", text)

            return TranscriptResult(
                text=text,
                language=locale_hint[:2] if locale_hint else None,
            )

        except Exception as e:
            LOG.exception("Parakeet transcription error: %s", e)
            return TranscriptResult(
                text=f"[Transcription error: {e}]",
                confidence=0.0,
            )

    def set_model(self, model_name: str) -> bool:
        """Set a new model.

        Args:
            model_name: onnx-asr model name.

        Returns:
            True if model loaded successfully.
        """
        self._model_name = model_name
        return self._load_model()
