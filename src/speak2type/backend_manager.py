"""Backend dependency and model management for speak2type.

Provides a central registry of backend specifications and handles
pip installation of dependencies and model downloads in userspace.
"""

import importlib
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackendSpec:
    """Specification for a speech recognition backend."""

    id: str
    name: str
    description: str
    pip_packages: list[str]
    check_import: str
    has_models: bool = False
    model_manager_module: str | None = None
    model_manager_class: str | None = None


BACKEND_SPECS: dict[str, BackendSpec] = {
    "parakeet": BackendSpec(
        id="parakeet",
        name="Parakeet TDT (NVIDIA)",
        description="Fast local speech recognition using NVIDIA Parakeet ONNX models. "
        "English and multilingual variants available (~600 MB).",
        pip_packages=["onnx-asr>=0.7.0", "onnxruntime>=1.16.0", "numpy>=1.24.0"],
        check_import="onnx_asr",
        has_models=True,
        model_manager_module="speak2type.model_managers.parakeet",
        model_manager_class="ParakeetModelManager",
    ),
    "whisper": BackendSpec(
        id="whisper",
        name="Whisper.cpp",
        description="OpenAI Whisper via whisper.cpp. Multiple model sizes from "
        "tiny (~75 MB) to large (~3 GB).",
        pip_packages=["pywhispercpp>=1.3.0", "numpy>=1.24.0"],
        check_import="pywhispercpp",
        has_models=True,
    ),
    "http": BackendSpec(
        id="http",
        name="HTTP Backend",
        description="Send audio to a remote transcription API. "
        "Supports generic and OpenAI-compatible endpoints.",
        pip_packages=["httpx>=0.25.0"],
        check_import="httpx",
        has_models=False,
    ),
}


class BackendManager:
    """Manages backend dependency installation and status checks."""

    def is_deps_installed(self, backend_id: str) -> bool:
        """Check if a backend's Python dependencies are importable.

        Args:
            backend_id: Backend identifier from BACKEND_SPECS.

        Returns:
            True if the check_import module can be imported.

        Raises:
            KeyError: If backend_id is not in BACKEND_SPECS.
        """
        spec = BACKEND_SPECS[backend_id]
        try:
            importlib.import_module(spec.check_import)
            return True
        except ImportError:
            return False

    def install_deps(self, backend_id: str) -> subprocess.CompletedProcess[str]:
        """Install a backend's pip dependencies in userspace.

        Runs ``pip install --user`` with the packages listed in the backend spec.

        Args:
            backend_id: Backend identifier from BACKEND_SPECS.

        Returns:
            CompletedProcess with stdout/stderr from pip.

        Raises:
            KeyError: If backend_id is not in BACKEND_SPECS.
            subprocess.CalledProcessError: If pip returns a non-zero exit code.
        """
        spec = BACKEND_SPECS[backend_id]
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--user",
            *spec.pip_packages,
        ]
        LOG.info("Installing deps for %s: %s", backend_id, " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            LOG.error("pip install failed for %s: %s", backend_id, result.stderr)
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        LOG.info("Deps installed for %s", backend_id)
        return result

    def uninstall_deps(self, backend_id: str) -> subprocess.CompletedProcess[str]:
        """Uninstall a backend's pip dependencies from userspace.

        Args:
            backend_id: Backend identifier from BACKEND_SPECS.

        Returns:
            CompletedProcess with stdout/stderr from pip.

        Raises:
            KeyError: If backend_id is not in BACKEND_SPECS.
            subprocess.CalledProcessError: If pip returns a non-zero exit code.
        """
        spec = BACKEND_SPECS[backend_id]
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "--yes",
            *spec.pip_packages,
        ]
        LOG.info("Uninstalling deps for %s: %s", backend_id, " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            LOG.error("pip uninstall failed for %s: %s", backend_id, result.stderr)
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        LOG.info("Deps uninstalled for %s", backend_id)
        return result

    def get_model_manager(self, backend_id: str) -> object | None:
        """Instantiate the model manager for a backend, if it has one.

        Args:
            backend_id: Backend identifier from BACKEND_SPECS.

        Returns:
            Model manager instance, or None if the backend has no models
            or the manager module cannot be imported.

        Raises:
            KeyError: If backend_id is not in BACKEND_SPECS.
        """
        spec = BACKEND_SPECS[backend_id]
        if not spec.has_models or not spec.model_manager_module or not spec.model_manager_class:
            return None
        try:
            module = importlib.import_module(spec.model_manager_module)
            cls = getattr(module, spec.model_manager_class)
            return cls()
        except (ImportError, AttributeError) as e:
            LOG.error("Cannot load model manager for %s: %s", backend_id, e)
            return None

    def get_install_status(self, backend_id: str) -> dict[str, bool | str | None]:
        """Get comprehensive install status for a backend.

        Args:
            backend_id: Backend identifier from BACKEND_SPECS.

        Returns:
            Dict with keys: deps_installed, has_models, model_installed, model_name.

        Raises:
            KeyError: If backend_id is not in BACKEND_SPECS.
        """
        spec = BACKEND_SPECS[backend_id]
        deps_installed = self.is_deps_installed(backend_id)

        status: dict[str, bool | str | None] = {
            "deps_installed": deps_installed,
            "has_models": spec.has_models,
            "model_installed": False,
            "model_name": None,
        }

        if deps_installed and spec.has_models:
            manager = self.get_model_manager(backend_id)
            if manager is not None:
                installed = list(manager.list_installed_models())
                if installed:
                    status["model_installed"] = True
                    status["model_name"] = installed[0][0]

        return status
