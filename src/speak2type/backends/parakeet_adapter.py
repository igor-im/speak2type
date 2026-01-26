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
from typing import TYPE_CHECKING

import numpy as np

from ..types import AudioSegment, TranscriptResult, Segment

if TYPE_CHECKING:
    from onnx_asr import ONNXModel

LOG = logging.getLogger(__name__)

# Check if onnx-asr is available
try:
    from onnx_asr import ONNXModel
    import onnxruntime
    PARAKEET_AVAILABLE = True
except ImportError:
    PARAKEET_AVAILABLE = False
    LOG.warning("onnx-asr not available. Install with: pip install onnx-asr")


def get_xdg_data_home() -> Path:
    """Get XDG_DATA_HOME directory."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def get_model_dir() -> Path:
    """Get the default model directory for Parakeet."""
    return get_xdg_data_home() / "speak2type" / "models" / "parakeet"


class ParakeetBackend:
    """Parakeet ONNX speech recognition backend.

    Uses onnx-asr to run NVIDIA Parakeet TDT models for high-performance
    transcription with CPU or CUDA acceleration.

    Supported models:
    - nvidia/parakeet-tdt-0.6b-v2 (English)
    - nvidia/parakeet-tdt-0.6b-v3-multilingual (Multilingual)
    """

    # Default model identifiers
    DEFAULT_MODEL = "nvidia/parakeet-tdt-0.6b-v2"
    MULTILINGUAL_MODEL = "nvidia/parakeet-tdt-0.6b-v3-multilingual"

    def __init__(
        self,
        model_name: str | None = None,
        model_path: str | Path | None = None,
        use_cuda: bool = False,
        num_threads: int = 4,
    ) -> None:
        """Initialize the Parakeet backend.

        Args:
            model_name: HuggingFace model name (e.g., "nvidia/parakeet-tdt-0.6b-v2").
            model_path: Local path to ONNX model directory.
            use_cuda: Whether to use CUDA for inference.
            num_threads: Number of threads for CPU inference.
        """
        self._model: "ONNXModel | None" = None
        self._model_name = model_name or self.DEFAULT_MODEL
        self._model_path: Path | None = None
        self._use_cuda = use_cuda
        self._num_threads = num_threads

        if not PARAKEET_AVAILABLE:
            LOG.error("Parakeet not available")
            return

        if model_path:
            self._load_from_path(Path(model_path))
        else:
            self._load_from_name(self._model_name)

    @property
    def id(self) -> str:
        return "parakeet"

    @property
    def name(self) -> str:
        return "Parakeet TDT (ONNX)"

    @property
    def is_available(self) -> bool:
        """Check if Parakeet is available and model is loaded."""
        return PARAKEET_AVAILABLE and self._model is not None

    def _get_session_options(self) -> "onnxruntime.SessionOptions":
        """Get ONNX Runtime session options."""
        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = self._num_threads
        opts.inter_op_num_threads = self._num_threads
        opts.graph_optimization_level = (
            onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        return opts

    def _get_providers(self) -> list[str]:
        """Get execution providers based on configuration."""
        if self._use_cuda:
            # Check if CUDA is available
            providers = onnxruntime.get_available_providers()
            if "CUDAExecutionProvider" in providers:
                return ["CUDAExecutionProvider", "CPUExecutionProvider"]
            LOG.warning("CUDA requested but not available, falling back to CPU")

        return ["CPUExecutionProvider"]

    def _load_from_name(self, model_name: str) -> bool:
        """Load model from HuggingFace model name.

        Args:
            model_name: HuggingFace model name.

        Returns:
            True if model loaded successfully.
        """
        if not PARAKEET_AVAILABLE:
            return False

        try:
            LOG.info("Loading Parakeet model: %s", model_name)

            # onnx-asr will download from HuggingFace if not cached
            self._model = ONNXModel.from_pretrained(
                model_name,
                session_options=self._get_session_options(),
                providers=self._get_providers(),
            )
            self._model_name = model_name

            LOG.info("Parakeet model loaded successfully")
            return True

        except Exception as e:
            LOG.error("Failed to load Parakeet model: %s", e)
            self._model = None
            return False

    def _load_from_path(self, model_path: Path) -> bool:
        """Load model from local path.

        Args:
            model_path: Path to model directory.

        Returns:
            True if model loaded successfully.
        """
        if not PARAKEET_AVAILABLE:
            return False

        if not model_path.exists():
            LOG.error("Model path does not exist: %s", model_path)
            return False

        try:
            LOG.info("Loading Parakeet model from: %s", model_path)

            self._model = ONNXModel(
                str(model_path),
                session_options=self._get_session_options(),
                providers=self._get_providers(),
            )
            self._model_path = model_path

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

            # Transcribe using onnx-asr
            result = self._model.transcribe(
                audio_float,
                sample_rate=segment.format.sample_rate,
            )

            # Extract text and segments
            text = ""
            segments_list = []

            if isinstance(result, str):
                # Simple string result
                text = result.strip()
            elif hasattr(result, "text"):
                # Result object with text attribute
                text = result.text.strip() if result.text else ""

                # Extract segments if available
                if hasattr(result, "segments") and result.segments:
                    for seg in result.segments:
                        segment_obj = Segment(
                            text=getattr(seg, "text", "").strip(),
                            start_ms=int(getattr(seg, "start", 0) * 1000),
                            end_ms=int(getattr(seg, "end", 0) * 1000),
                            confidence=getattr(seg, "confidence", None),
                        )
                        if segment_obj.text:
                            segments_list.append(segment_obj)
            elif isinstance(result, dict):
                # Dictionary result
                text = result.get("text", "").strip()

            LOG.info("Parakeet transcription: '%s'", text)

            return TranscriptResult(
                text=text,
                segments=segments_list if segments_list else None,
                language=locale_hint[:2] if locale_hint else None,
            )

        except Exception as e:
            LOG.exception("Parakeet transcription error: %s", e)
            return TranscriptResult(
                text=f"[Transcription error: {e}]",
                confidence=0.0,
            )

    def set_model(self, model_name: str | None = None, model_path: Path | None = None) -> bool:
        """Set a new model.

        Args:
            model_name: HuggingFace model name.
            model_path: Local path to model directory.

        Returns:
            True if model loaded successfully.
        """
        if model_path:
            return self._load_from_path(model_path)
        elif model_name:
            return self._load_from_name(model_name)
        return False

    def set_use_cuda(self, use_cuda: bool) -> None:
        """Set whether to use CUDA.

        Args:
            use_cuda: Whether to use CUDA for inference.

        Note: Requires reloading the model to take effect.
        """
        if self._use_cuda != use_cuda:
            self._use_cuda = use_cuda
            # Reload model with new providers
            if self._model_path:
                self._load_from_path(self._model_path)
            elif self._model_name:
                self._load_from_name(self._model_name)

    def set_num_threads(self, num_threads: int) -> None:
        """Set number of threads for CPU inference.

        Args:
            num_threads: Number of threads.

        Note: Requires reloading the model to take effect.
        """
        if self._num_threads != num_threads:
            self._num_threads = num_threads
            # Reload model with new thread count
            if self._model_path:
                self._load_from_path(self._model_path)
            elif self._model_name:
                self._load_from_name(self._model_name)
