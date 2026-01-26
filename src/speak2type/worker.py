"""Worker thread for background transcription."""

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable

from gi.repository import GLib

from .types import AudioSegment, Backend, TranscriptResult

LOG = logging.getLogger(__name__)


@dataclass
class TranscriptionJob:
    """A transcription job to be processed by the worker."""
    segment: AudioSegment
    locale_hint: str
    options: dict | None = None


class TranscriptionWorker:
    """Background worker for speech transcription.

    Processes audio segments in a background thread to avoid blocking
    the IBus main loop.
    """

    def __init__(
        self,
        backend: Backend,
        on_result: Callable[[TranscriptResult], None],
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Initialize the worker.

        Args:
            backend: Speech recognition backend to use.
            on_result: Callback for transcription results (called in main loop).
            on_error: Callback for errors (called in main loop).
        """
        self._backend = backend
        self._on_result = on_result
        self._on_error = on_error

        self._job_queue: queue.Queue[TranscriptionJob | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        """Return whether the worker thread is running."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def backend(self) -> Backend:
        """Return the current backend."""
        return self._backend

    @backend.setter
    def backend(self, value: Backend) -> None:
        """Set the backend (thread-safe)."""
        self._backend = value

    def start(self) -> None:
        """Start the worker thread."""
        if self.is_running:
            LOG.warning("Worker already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="speak2type-worker",
            daemon=True,
        )
        self._thread.start()
        LOG.info("Worker thread started")

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the worker thread.

        Args:
            timeout: Maximum time to wait for thread to stop.
        """
        if not self.is_running:
            return

        self._stop_event.set()
        self._job_queue.put(None)  # Wake up the thread

        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                LOG.warning("Worker thread did not stop within timeout")
            else:
                LOG.info("Worker thread stopped")

        self._thread = None

    def submit(
        self,
        segment: AudioSegment,
        locale_hint: str = "en_US",
        options: dict | None = None,
    ) -> None:
        """Submit a transcription job.

        Args:
            segment: Audio segment to transcribe.
            locale_hint: Suggested locale.
            options: Backend-specific options.
        """
        if not self.is_running:
            LOG.warning("Worker not running, starting automatically")
            self.start()

        job = TranscriptionJob(
            segment=segment,
            locale_hint=locale_hint,
            options=options,
        )
        self._job_queue.put(job)
        LOG.debug("Submitted transcription job (%.2fs audio)", segment.duration_seconds)

    def _run(self) -> None:
        """Worker thread main loop."""
        LOG.debug("Worker thread running")

        while not self._stop_event.is_set():
            try:
                job = self._job_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if job is None:
                # Shutdown signal
                break

            try:
                self._process_job(job)
            except Exception as e:
                LOG.exception("Error processing job: %s", e)
                self._report_error(e)
            finally:
                self._job_queue.task_done()

        LOG.debug("Worker thread exiting")

    def _process_job(self, job: TranscriptionJob) -> None:
        """Process a single transcription job."""
        LOG.debug(
            "Processing job: %.2fs audio, locale=%s",
            job.segment.duration_seconds,
            job.locale_hint,
        )

        result = self._backend.transcribe(
            segment=job.segment,
            locale_hint=job.locale_hint,
            options=job.options,
        )

        LOG.info("Transcription result: '%s'", result.text)

        # Schedule callback in main loop
        GLib.idle_add(self._deliver_result, result)

    def _deliver_result(self, result: TranscriptResult) -> bool:
        """Deliver result in main loop context."""
        try:
            self._on_result(result)
        except Exception as e:
            LOG.exception("Error in result callback: %s", e)
        return False  # Don't repeat

    def _report_error(self, error: Exception) -> None:
        """Report error in main loop context."""
        if self._on_error:
            GLib.idle_add(self._on_error, error)

    def wait_for_completion(self, timeout: float | None = None) -> bool:
        """Wait for all pending jobs to complete.

        Args:
            timeout: Maximum time to wait, or None for infinite.

        Returns:
            True if all jobs completed, False if timeout.
        """
        try:
            self._job_queue.join()
            return True
        except Exception:
            return False
