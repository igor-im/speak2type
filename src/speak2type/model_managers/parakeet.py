"""Parakeet model manager for speak2type.

Handles model discovery, download, and verification for Parakeet ONNX models.
Uses XDG directories and supports pinned model versions with SHA256 verification.
"""

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

LOG = logging.getLogger(__name__)


def get_xdg_data_home() -> Path:
    """Get XDG_DATA_HOME directory."""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def get_xdg_cache_home() -> Path:
    """Get XDG_CACHE_HOME directory."""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".cache"


@dataclass
class ModelSpec:
    """Specification for a Parakeet model."""

    id: str  # e.g., "nvidia/parakeet-tdt-0.6b-v2"
    name: str  # Human-readable name
    revision: str  # Git revision/commit hash
    sha256: str  # SHA256 of the ONNX bundle/files
    license: str  # License type
    languages: list[str]  # Supported languages
    size_mb: int  # Approximate size in MB
    description: str = ""


# Pinned model specifications for reproducibility and security
PINNED_MODELS: dict[str, ModelSpec] = {
    "nvidia/parakeet-tdt-0.6b-v2": ModelSpec(
        id="nvidia/parakeet-tdt-0.6b-v2",
        name="Parakeet TDT 0.6B v2 (English)",
        revision="main",  # TODO: Pin to specific commit
        sha256="",  # TODO: Compute and pin SHA256
        license="CC-BY-4.0",
        languages=["en"],
        size_mb=600,
        description="English-only model, fast inference",
    ),
    "nvidia/parakeet-tdt-0.6b-v3-multilingual": ModelSpec(
        id="nvidia/parakeet-tdt-0.6b-v3-multilingual",
        name="Parakeet TDT 0.6B v3 (Multilingual)",
        revision="main",  # TODO: Pin to specific commit
        sha256="",  # TODO: Compute and pin SHA256
        license="CC-BY-4.0",
        languages=["en", "es", "fr", "de", "it", "pt", "nl", "ja", "ko", "zh"],
        size_mb=650,
        description="Multilingual model, supports 10+ languages",
    ),
}


class ParakeetModelManager:
    """Manager for Parakeet model download and verification."""

    def __init__(self, model_dir: Path | None = None, cache_dir: Path | None = None) -> None:
        """Initialize the model manager.

        Args:
            model_dir: Directory for model storage. Defaults to XDG_DATA_HOME.
            cache_dir: Directory for download cache. Defaults to XDG_CACHE_HOME.
        """
        self._model_dir = model_dir or (get_xdg_data_home() / "speak2type" / "models" / "parakeet")
        self._cache_dir = cache_dir or (get_xdg_cache_home() / "speak2type" / "parakeet")

        # Ensure directories exist
        self._model_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def model_dir(self) -> Path:
        """Get the model storage directory."""
        return self._model_dir

    @property
    def cache_dir(self) -> Path:
        """Get the download cache directory."""
        return self._cache_dir

    def list_available_models(self) -> list[ModelSpec]:
        """List all available (pinned) models.

        Returns:
            List of available model specifications.
        """
        return list(PINNED_MODELS.values())

    def list_installed_models(self) -> Iterator[tuple[str, Path]]:
        """List installed models.

        Yields:
            Tuples of (model_id, model_path).
        """
        if not self._model_dir.exists():
            return

        for item in self._model_dir.iterdir():
            if item.is_dir():
                # Check if it looks like a valid model
                if (item / "model.onnx").exists() or (item / "config.json").exists():
                    yield item.name, item

    def get_model_path(self, model_id: str) -> Path | None:
        """Get the path to an installed model.

        Args:
            model_id: Model identifier.

        Returns:
            Path to model directory or None if not installed.
        """
        # Normalize model ID to directory name
        dir_name = model_id.replace("/", "_")
        model_path = self._model_dir / dir_name

        if model_path.exists():
            return model_path

        return None

    def is_installed(self, model_id: str) -> bool:
        """Check if a model is installed.

        Args:
            model_id: Model identifier.

        Returns:
            True if model is installed.
        """
        return self.get_model_path(model_id) is not None

    def download_model(
        self,
        model_id: str,
        force: bool = False,
        progress_callback: callable | None = None,
    ) -> Path | None:
        """Download a model from HuggingFace.

        Args:
            model_id: Model identifier (e.g., "nvidia/parakeet-tdt-0.6b-v2").
            force: Force re-download even if already installed.
            progress_callback: Optional callback for progress updates.

        Returns:
            Path to installed model or None if download failed.
        """
        # Check if already installed
        if not force and self.is_installed(model_id):
            LOG.info("Model already installed: %s", model_id)
            return self.get_model_path(model_id)

        # Get pinned spec if available
        spec = PINNED_MODELS.get(model_id)

        try:
            # Use huggingface_hub for download
            from huggingface_hub import snapshot_download

            LOG.info("Downloading model: %s", model_id)

            # Download to cache first
            revision = spec.revision if spec else "main"
            cache_path = snapshot_download(
                repo_id=model_id,
                revision=revision,
                cache_dir=self._cache_dir,
            )

            # Move to model directory
            dir_name = model_id.replace("/", "_")
            model_path = self._model_dir / dir_name

            if model_path.exists():
                shutil.rmtree(model_path)

            shutil.copytree(cache_path, model_path)

            # Verify SHA256 if pinned
            if spec and spec.sha256:
                if not self._verify_sha256(model_path, spec.sha256):
                    LOG.error("SHA256 verification failed for %s", model_id)
                    shutil.rmtree(model_path)
                    return None

            LOG.info("Model installed: %s -> %s", model_id, model_path)
            return model_path

        except ImportError:
            LOG.error("huggingface_hub not installed. Install with: pip install huggingface_hub")
            return None
        except Exception as e:
            LOG.error("Failed to download model %s: %s", model_id, e)
            return None

    def _verify_sha256(self, model_path: Path, expected_sha256: str) -> bool:
        """Verify SHA256 of model files.

        Args:
            model_path: Path to model directory.
            expected_sha256: Expected SHA256 hash.

        Returns:
            True if verification passed.
        """
        if not expected_sha256:
            LOG.warning("No SHA256 specified for verification")
            return True

        # Compute SHA256 of all files
        sha256 = hashlib.sha256()

        for file_path in sorted(model_path.rglob("*")):
            if file_path.is_file():
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha256.update(chunk)

        computed = sha256.hexdigest()

        if computed != expected_sha256:
            LOG.error("SHA256 mismatch: expected %s, got %s", expected_sha256, computed)
            return False

        LOG.info("SHA256 verification passed")
        return True

    def remove_model(self, model_id: str) -> bool:
        """Remove an installed model.

        Args:
            model_id: Model identifier.

        Returns:
            True if model was removed.
        """
        model_path = self.get_model_path(model_id)
        if model_path is None:
            LOG.warning("Model not installed: %s", model_id)
            return False

        try:
            shutil.rmtree(model_path)
            LOG.info("Removed model: %s", model_id)
            return True
        except Exception as e:
            LOG.error("Failed to remove model %s: %s", model_id, e)
            return False

    def get_default_model_for_locale(self, locale: str) -> str:
        """Get the recommended model for a locale.

        Args:
            locale: Locale string (e.g., "en_US").

        Returns:
            Model identifier.
        """
        lang = locale[:2].lower()

        # Check multilingual model's supported languages
        multilingual = PINNED_MODELS.get("nvidia/parakeet-tdt-0.6b-v3-multilingual")
        if multilingual and lang in multilingual.languages:
            return multilingual.id

        # Fall back to English model
        return "nvidia/parakeet-tdt-0.6b-v2"
