"""Tests for the backend manager module."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from speak2type.backend_manager import BACKEND_SPECS, BackendManager, BackendSpec


class TestBackendSpec:
    """Tests for BackendSpec dataclass and BACKEND_SPECS registry."""

    def test_all_specs_have_required_fields(self) -> None:
        """Every spec must have non-empty id, name, pip_packages, check_import."""
        for backend_id, spec in BACKEND_SPECS.items():
            assert spec.id == backend_id
            assert spec.name
            assert spec.pip_packages
            assert spec.check_import

    def test_known_backends_present(self) -> None:
        """Parakeet, whisper, and http backends must be registered."""
        assert "parakeet" in BACKEND_SPECS
        assert "whisper" in BACKEND_SPECS
        assert "http" in BACKEND_SPECS

    def test_parakeet_has_models(self) -> None:
        """Parakeet backend must declare model support."""
        spec = BACKEND_SPECS["parakeet"]
        assert spec.has_models is True
        assert spec.model_manager_module is not None
        assert spec.model_manager_class is not None

    def test_http_has_no_models(self) -> None:
        """HTTP backend should not declare model support."""
        spec = BACKEND_SPECS["http"]
        assert spec.has_models is False

    def test_spec_is_frozen(self) -> None:
        """BackendSpec should be immutable."""
        spec = BACKEND_SPECS["parakeet"]
        with pytest.raises(AttributeError):
            spec.id = "modified"


class TestBackendManagerDepsCheck:
    """Tests for BackendManager.is_deps_installed."""

    def test_installed_when_import_succeeds(self) -> None:
        """Should return True when check_import module exists."""
        mgr = BackendManager()
        # 'json' is a stdlib module, always importable
        with patch.dict(BACKEND_SPECS, {
            "test": BackendSpec(
                id="test", name="Test", description="",
                pip_packages=["fake"], check_import="json",
            )
        }):
            assert mgr.is_deps_installed("test") is True

    def test_not_installed_when_import_fails(self) -> None:
        """Should return False when check_import module is missing."""
        mgr = BackendManager()
        with patch.dict(BACKEND_SPECS, {
            "test": BackendSpec(
                id="test", name="Test", description="",
                pip_packages=["fake"], check_import="nonexistent_module_xyz",
            )
        }):
            assert mgr.is_deps_installed("test") is False

    def test_unknown_backend_raises(self) -> None:
        """Should raise KeyError for unknown backend id."""
        mgr = BackendManager()
        with pytest.raises(KeyError):
            mgr.is_deps_installed("nonexistent")


class TestBackendManagerInstall:
    """Tests for BackendManager.install_deps."""

    @patch("speak2type.backend_manager.subprocess.run")
    def test_install_calls_pip_with_user_flag(self, mock_run: MagicMock) -> None:
        """Install should run pip install --user with correct packages."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        mgr = BackendManager()
        mgr.install_deps("parakeet")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--user" in cmd
        assert "onnx-asr>=0.7.0" in cmd

    @patch("speak2type.backend_manager.subprocess.run")
    def test_install_raises_on_failure(self, mock_run: MagicMock) -> None:
        """Install should raise CalledProcessError on pip failure."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        mgr = BackendManager()
        with pytest.raises(subprocess.CalledProcessError):
            mgr.install_deps("parakeet")

    @patch("speak2type.backend_manager.subprocess.run")
    def test_uninstall_calls_pip(self, mock_run: MagicMock) -> None:
        """Uninstall should run pip uninstall --yes."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ok", stderr=""
        )
        mgr = BackendManager()
        mgr.uninstall_deps("http")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "uninstall" in cmd
        assert "--yes" in cmd
        assert "httpx>=0.25.0" in cmd


class TestBackendManagerModelManager:
    """Tests for BackendManager.get_model_manager."""

    def test_returns_none_for_no_model_backend(self) -> None:
        """HTTP backend has no models, should return None."""
        mgr = BackendManager()
        assert mgr.get_model_manager("http") is None

    def test_returns_manager_for_parakeet(self) -> None:
        """Parakeet backend should return a ParakeetModelManager."""
        mgr = BackendManager()
        model_mgr = mgr.get_model_manager("parakeet")
        assert model_mgr is not None
        assert hasattr(model_mgr, "list_available_models")
        assert hasattr(model_mgr, "download_model")


class TestBackendManagerStatus:
    """Tests for BackendManager.get_install_status."""

    def test_status_keys(self) -> None:
        """Status dict should have expected keys."""
        mgr = BackendManager()
        status = mgr.get_install_status("http")
        assert "deps_installed" in status
        assert "has_models" in status
        assert "model_installed" in status
        assert "model_name" in status

    def test_http_has_no_models_in_status(self) -> None:
        """HTTP backend status should report has_models=False."""
        mgr = BackendManager()
        status = mgr.get_install_status("http")
        assert status["has_models"] is False
        assert status["model_installed"] is False
