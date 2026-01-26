"""Base backend classes and registry."""

import logging
from typing import TYPE_CHECKING

from ..types import AudioSegment, Backend, TranscriptResult

if TYPE_CHECKING:
    from typing import Dict, Type

LOG = logging.getLogger(__name__)


class PlaceholderBackend:
    """Placeholder backend for testing when no real backend is configured."""

    @property
    def id(self) -> str:
        return "placeholder"

    @property
    def name(self) -> str:
        return "Placeholder (No Backend)"

    def transcribe(
        self,
        segment: AudioSegment,
        locale_hint: str,
        options: dict | None = None,
    ) -> TranscriptResult:
        """Return a placeholder result."""
        LOG.warning("Placeholder backend called - configure a real backend")
        return TranscriptResult(
            text=f"[Placeholder: {segment.duration_seconds:.1f}s audio, locale={locale_hint}]",
            confidence=0.0,
        )


class BackendRegistry:
    """Registry for managing speech recognition backends."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._backends: Dict[str, Backend] = {}
        self._current_id: str | None = None

        # Register placeholder backend
        self.register(PlaceholderBackend())

    def register(self, backend: Backend) -> None:
        """Register a backend.

        Args:
            backend: Backend instance to register.
        """
        if backend.id in self._backends:
            LOG.warning("Overwriting existing backend: %s", backend.id)

        self._backends[backend.id] = backend
        LOG.info("Registered backend: %s (%s)", backend.id, backend.name)

    def unregister(self, backend_id: str) -> None:
        """Unregister a backend.

        Args:
            backend_id: ID of backend to unregister.
        """
        if backend_id in self._backends:
            del self._backends[backend_id]
            LOG.info("Unregistered backend: %s", backend_id)

            if self._current_id == backend_id:
                self._current_id = None

    def get(self, backend_id: str) -> Backend | None:
        """Get a backend by ID.

        Args:
            backend_id: ID of backend to get.

        Returns:
            Backend instance or None.
        """
        return self._backends.get(backend_id)

    @property
    def available_backends(self) -> list[str]:
        """Return list of available backend IDs."""
        return list(self._backends.keys())

    @property
    def current(self) -> Backend | None:
        """Return the current active backend."""
        if self._current_id is None:
            return None
        return self._backends.get(self._current_id)

    def set_current(self, backend_id: str) -> bool:
        """Set the current active backend.

        Args:
            backend_id: ID of backend to make active.

        Returns:
            True if backend was found and set.
        """
        if backend_id not in self._backends:
            LOG.error("Unknown backend: %s", backend_id)
            return False

        self._current_id = backend_id
        LOG.info("Set current backend: %s", backend_id)
        return True

    def get_or_placeholder(self) -> Backend:
        """Return current backend or placeholder if none set."""
        if self._current_id and self._current_id in self._backends:
            return self._backends[self._current_id]
        return self._backends.get("placeholder", PlaceholderBackend())


# Global registry instance
_registry: BackendRegistry | None = None


def get_registry() -> BackendRegistry:
    """Get the global backend registry."""
    global _registry
    if _registry is None:
        _registry = BackendRegistry()
    return _registry
