"""Tests for speak2type backends."""

import pytest

from speak2type.backends.base import BackendRegistry, PlaceholderBackend, get_registry
from speak2type.backends import (
    VOSK_AVAILABLE,
    WHISPER_AVAILABLE,
    register_default_backends,
)
from speak2type.types import AudioSegment, AudioFormat


class TestPlaceholderBackend:
    """Tests for PlaceholderBackend."""

    def test_id_and_name(self):
        """Test backend identification."""
        backend = PlaceholderBackend()
        assert backend.id == "placeholder"
        assert "Placeholder" in backend.name

    def test_transcribe_returns_result(self, sample_audio_segment):
        """Test that transcribe returns a valid result."""
        backend = PlaceholderBackend()
        result = backend.transcribe(sample_audio_segment, "en_US")

        assert result.text is not None
        assert "Placeholder" in result.text
        assert result.confidence == 0.0


class TestBackendRegistry:
    """Tests for BackendRegistry."""

    def test_register_and_get(self):
        """Test registering and retrieving a backend."""
        registry = BackendRegistry()
        backend = PlaceholderBackend()

        registry.register(backend)
        retrieved = registry.get("placeholder")

        assert retrieved is backend

    def test_available_backends(self):
        """Test listing available backends."""
        registry = BackendRegistry()
        # Placeholder is registered by default
        assert "placeholder" in registry.available_backends

    def test_set_current(self):
        """Test setting current backend."""
        registry = BackendRegistry()

        assert registry.set_current("placeholder") is True
        assert registry.current is not None
        assert registry.current.id == "placeholder"

    def test_set_unknown_backend(self):
        """Test setting unknown backend fails."""
        registry = BackendRegistry()
        assert registry.set_current("nonexistent") is False

    def test_unregister(self):
        """Test unregistering a backend."""
        registry = BackendRegistry()
        registry.set_current("placeholder")
        registry.unregister("placeholder")

        assert "placeholder" not in registry.available_backends
        assert registry.current is None

    def test_get_or_placeholder(self):
        """Test fallback to placeholder."""
        registry = BackendRegistry()
        # No current set
        backend = registry.get_or_placeholder()
        assert backend.id == "placeholder"

        # Set current
        registry.set_current("placeholder")
        backend = registry.get_or_placeholder()
        assert backend.id == "placeholder"


class TestGlobalRegistry:
    """Tests for global registry singleton."""

    def test_singleton(self):
        """Test that get_registry returns same instance."""
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2


class TestRegisterDefaultBackends:
    """Tests for register_default_backends function."""

    def test_registers_placeholder(self):
        """Test that placeholder is always registered."""
        registry = BackendRegistry()
        register_default_backends(registry)
        assert "placeholder" in registry.available_backends

    @pytest.mark.skipif(not VOSK_AVAILABLE, reason="vosk not installed")
    def test_registers_vosk_if_available(self):
        """Test that Vosk is registered if available."""
        registry = BackendRegistry()
        register_default_backends(registry)
        # Note: Vosk may not register if no model is available
        # Just verify no errors occur

    @pytest.mark.skipif(not WHISPER_AVAILABLE, reason="pywhispercpp not installed")
    def test_registers_whisper_if_available(self):
        """Test that Whisper is registered if available."""
        registry = BackendRegistry()
        register_default_backends(registry)
        # Note: Whisper may not register if no model is available
        # Just verify no errors occur


@pytest.mark.skipif(not VOSK_AVAILABLE, reason="vosk not installed")
class TestVoskBackend:
    """Tests for VoskBackend."""

    def test_backend_id(self):
        """Test Vosk backend identification."""
        from speak2type.backends.vosk_adapter import VoskBackend

        backend = VoskBackend()
        assert backend.id == "vosk"
        assert "Vosk" in backend.name

    def test_transcribe_without_model(self, sample_audio_segment):
        """Test transcription fails gracefully without model."""
        from speak2type.backends.vosk_adapter import VoskBackend

        backend = VoskBackend(model_path="/nonexistent/path")
        result = backend.transcribe(sample_audio_segment, "en_US")
        # Should return error message, not crash
        assert result.text is not None


@pytest.mark.skipif(not WHISPER_AVAILABLE, reason="pywhispercpp not installed")
class TestWhisperBackend:
    """Tests for WhisperBackend."""

    def test_backend_id(self):
        """Test Whisper backend identification."""
        from speak2type.backends.whisper_adapter import WhisperBackend

        backend = WhisperBackend()
        assert backend.id == "whisper"
        assert "Whisper" in backend.name

    def test_transcribe_without_model(self, sample_audio_segment):
        """Test transcription fails gracefully without model."""
        from speak2type.backends.whisper_adapter import WhisperBackend

        backend = WhisperBackend(model_path="/nonexistent/path")
        result = backend.transcribe(sample_audio_segment, "en_US")
        # Should return error message, not crash
        assert result.text is not None
