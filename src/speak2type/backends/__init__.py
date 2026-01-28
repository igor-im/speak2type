"""Speech recognition backends for speak2type."""

import logging

from .base import BackendRegistry, get_registry, PlaceholderBackend

LOG = logging.getLogger(__name__)

# Try to import Vosk backend
try:
    from .vosk_adapter import VoskBackend, VOSK_AVAILABLE
except ImportError:
    VoskBackend = None
    VOSK_AVAILABLE = False
    LOG.warning("Vosk backend not available", exc_info=True)

# Try to import Whisper backend
try:
    from .whisper_adapter import WhisperBackend, WHISPER_AVAILABLE
except ImportError:
    WhisperBackend = None
    WHISPER_AVAILABLE = False
    LOG.warning("Whisper backend not available", exc_info=True)

# Try to import Parakeet backend
try:
    from .parakeet_adapter import ParakeetBackend, PARAKEET_AVAILABLE
except ImportError:
    ParakeetBackend = None
    PARAKEET_AVAILABLE = False
    LOG.warning("Parakeet backend not available", exc_info=True)

# Try to import HTTP backend
try:
    from .http_adapter import HttpBackend, HttpDialect, HTTPX_AVAILABLE
except ImportError:
    HttpBackend = None
    HttpDialect = None
    HTTPX_AVAILABLE = False
    LOG.warning("HTTP backend not available", exc_info=True)

__all__ = [
    "BackendRegistry",
    "get_registry",
    "PlaceholderBackend",
    "VoskBackend",
    "VOSK_AVAILABLE",
    "WhisperBackend",
    "WHISPER_AVAILABLE",
    "ParakeetBackend",
    "PARAKEET_AVAILABLE",
    "HttpBackend",
    "HttpDialect",
    "HTTPX_AVAILABLE",
    "register_default_backends",
]


def register_default_backends(registry: BackendRegistry | None = None) -> None:
    """Register available backends with the registry.

    Args:
        registry: Registry to use, or None for global registry.
    """
    if registry is None:
        registry = get_registry()

    # Try to register Vosk
    if VOSK_AVAILABLE and VoskBackend is not None:
        try:
            backend = VoskBackend()
            if backend.is_available:
                registry.register(backend)
            else:
                LOG.info("Vosk available but no model loaded")
        except Exception as e:
            LOG.warning("Failed to initialize Vosk: %s", e)

    # Try to register Whisper
    if WHISPER_AVAILABLE and WhisperBackend is not None:
        try:
            backend = WhisperBackend()
            if backend.is_available:
                registry.register(backend)
            else:
                LOG.info("Whisper available but no model loaded")
        except Exception as e:
            LOG.warning("Failed to initialize Whisper: %s", e)

    # Try to register Parakeet
    if PARAKEET_AVAILABLE and ParakeetBackend is not None:
        try:
            backend = ParakeetBackend()
            if backend.is_available:
                registry.register(backend)
            else:
                LOG.info("Parakeet available but no model loaded")
        except Exception as e:
            LOG.warning("Failed to initialize Parakeet: %s", e)

    # Try to register HTTP backend
    if HTTPX_AVAILABLE and HttpBackend is not None:
        try:
            backend = HttpBackend()
            if backend.is_available:
                registry.register(backend)
            else:
                LOG.info("HTTP backend available but not configured")
        except Exception as e:
            LOG.warning("Failed to initialize HTTP backend: %s", e)
