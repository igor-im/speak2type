#!/usr/bin/env python3
"""Benchmark harness for speak2type backends.

Measures:
- RTF (Real-Time Factor) for different audio durations
- Latency (release-to-first-text, release-to-final)
- CPU utilization during inference
- Peak memory usage

Usage:
    python scripts/benchmark.py --backend parakeet --duration 10
    python scripts/benchmark.py --backend vosk --samples audio/*.wav
"""

import argparse
import gc
import logging
import os
import resource
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from speak2type.types import AudioSegment, AudioFormat
from speak2type.backends import (
    VOSK_AVAILABLE,
    WHISPER_AVAILABLE,
    PARAKEET_AVAILABLE,
)

LOG = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""

    backend: str
    audio_duration_s: float
    transcription_time_s: float
    rtf: float  # Real-Time Factor
    cpu_percent: float
    peak_memory_mb: float
    text: str
    error: str | None = None


@dataclass
class BenchmarkSummary:
    """Summary of multiple benchmark runs."""

    backend: str
    runs: list[BenchmarkResult] = field(default_factory=list)

    @property
    def avg_rtf(self) -> float:
        if not self.runs:
            return 0.0
        return sum(r.rtf for r in self.runs) / len(self.runs)

    @property
    def min_rtf(self) -> float:
        if not self.runs:
            return 0.0
        return min(r.rtf for r in self.runs)

    @property
    def max_rtf(self) -> float:
        if not self.runs:
            return 0.0
        return max(r.rtf for r in self.runs)

    @property
    def avg_latency_s(self) -> float:
        if not self.runs:
            return 0.0
        return sum(r.transcription_time_s for r in self.runs) / len(self.runs)

    @property
    def peak_memory_mb(self) -> float:
        if not self.runs:
            return 0.0
        return max(r.peak_memory_mb for r in self.runs)


def generate_silence(duration_s: float, sample_rate: int = 16000) -> bytes:
    """Generate silent audio for testing.

    Args:
        duration_s: Duration in seconds.
        sample_rate: Sample rate in Hz.

    Returns:
        PCM bytes (S16LE).
    """
    num_samples = int(duration_s * sample_rate)
    return np.zeros(num_samples, dtype=np.int16).tobytes()


def generate_noise(duration_s: float, sample_rate: int = 16000) -> bytes:
    """Generate white noise audio for testing.

    Args:
        duration_s: Duration in seconds.
        sample_rate: Sample rate in Hz.

    Returns:
        PCM bytes (S16LE).
    """
    num_samples = int(duration_s * sample_rate)
    # Low amplitude noise
    noise = np.random.randint(-1000, 1000, num_samples, dtype=np.int16)
    return noise.tobytes()


def load_wav_file(path: Path) -> tuple[bytes, int]:
    """Load a WAV file and return PCM data.

    Args:
        path: Path to WAV file.

    Returns:
        Tuple of (pcm_bytes, sample_rate).
    """
    import wave

    with wave.open(str(path), "rb") as wav:
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    # Assume 16-bit mono
    return frames, sample_rate


def get_peak_memory_mb() -> float:
    """Get peak memory usage in MB."""
    rusage = resource.getrusage(resource.RUSAGE_SELF)
    # maxrss is in KB on Linux
    return rusage.ru_maxrss / 1024


def run_benchmark(
    backend,
    audio_segment: AudioSegment,
    warmup: bool = True,
) -> BenchmarkResult:
    """Run a single benchmark.

    Args:
        backend: Backend instance to benchmark.
        audio_segment: Audio to transcribe.
        warmup: Whether this is a warmup run.

    Returns:
        Benchmark result.
    """
    # Force garbage collection before measurement
    gc.collect()

    # Record start memory
    start_memory = get_peak_memory_mb()

    # Record start time
    start_time = time.perf_counter()

    # Run transcription
    try:
        result = backend.transcribe(audio_segment, "en_US")
        error = None
        text = result.text
    except Exception as e:
        error = str(e)
        text = ""

    # Record end time
    end_time = time.perf_counter()

    # Record peak memory
    peak_memory = get_peak_memory_mb()

    # Calculate metrics
    transcription_time = end_time - start_time
    audio_duration = audio_segment.duration_seconds
    rtf = transcription_time / audio_duration if audio_duration > 0 else 0

    return BenchmarkResult(
        backend=backend.id,
        audio_duration_s=audio_duration,
        transcription_time_s=transcription_time,
        rtf=rtf,
        cpu_percent=0.0,  # Would need psutil for accurate CPU measurement
        peak_memory_mb=peak_memory,
        text=text,
        error=error,
    )


def create_backend(backend_name: str):
    """Create a backend instance by name.

    Args:
        backend_name: Backend name (vosk, whisper, parakeet).

    Returns:
        Backend instance.
    """
    if backend_name == "vosk":
        if not VOSK_AVAILABLE:
            raise RuntimeError("Vosk not available")
        from speak2type.backends.vosk_adapter import VoskBackend
        return VoskBackend()

    elif backend_name == "whisper":
        if not WHISPER_AVAILABLE:
            raise RuntimeError("Whisper not available")
        from speak2type.backends.whisper_adapter import WhisperBackend
        return WhisperBackend()

    elif backend_name == "parakeet":
        if not PARAKEET_AVAILABLE:
            raise RuntimeError("Parakeet not available")
        from speak2type.backends.parakeet_adapter import ParakeetBackend
        return ParakeetBackend()

    else:
        raise ValueError(f"Unknown backend: {backend_name}")


def print_summary(summary: BenchmarkSummary) -> None:
    """Print benchmark summary."""
    print(f"\n{'=' * 60}")
    print(f"Benchmark Summary: {summary.backend}")
    print(f"{'=' * 60}")
    print(f"Runs: {len(summary.runs)}")
    print(f"Average RTF: {summary.avg_rtf:.3f}")
    print(f"Min RTF: {summary.min_rtf:.3f}")
    print(f"Max RTF: {summary.max_rtf:.3f}")
    print(f"Average Latency: {summary.avg_latency_s:.3f}s")
    print(f"Peak Memory: {summary.peak_memory_mb:.1f} MB")
    print(f"{'=' * 60}\n")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Benchmark speak2type backends")
    parser.add_argument(
        "--backend",
        choices=["vosk", "whisper", "parakeet", "all"],
        default="all",
        help="Backend to benchmark",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=10.0,
        help="Duration of synthetic audio in seconds",
    )
    parser.add_argument(
        "--samples",
        nargs="*",
        help="WAV files to use as samples",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of benchmark runs",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Number of warmup runs",
    )
    parser.add_argument(
        "--noise",
        action="store_true",
        help="Use white noise instead of silence for synthetic audio",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Determine backends to benchmark
    backends_to_test = []
    if args.backend == "all":
        if VOSK_AVAILABLE:
            backends_to_test.append("vosk")
        if WHISPER_AVAILABLE:
            backends_to_test.append("whisper")
        if PARAKEET_AVAILABLE:
            backends_to_test.append("parakeet")
    else:
        backends_to_test.append(args.backend)

    if not backends_to_test:
        print("No backends available to benchmark")
        return 1

    # Create audio segments
    segments = []
    if args.samples:
        for sample_path in args.samples:
            path = Path(sample_path)
            if path.exists():
                pcm, rate = load_wav_file(path)
                segments.append(
                    AudioSegment(pcm_bytes=pcm, format=AudioFormat(sample_rate=rate))
                )
                LOG.info("Loaded sample: %s (%.2fs)", path, len(pcm) / (rate * 2))
    else:
        # Generate synthetic audio
        generator = generate_noise if args.noise else generate_silence
        pcm = generator(args.duration)
        segments.append(
            AudioSegment(pcm_bytes=pcm, format=AudioFormat())
        )
        LOG.info("Generated %.2fs of %s", args.duration, "noise" if args.noise else "silence")

    # Run benchmarks
    for backend_name in backends_to_test:
        print(f"\nBenchmarking: {backend_name}")

        try:
            backend = create_backend(backend_name)
        except Exception as e:
            print(f"  Failed to create backend: {e}")
            continue

        if not backend.is_available:
            print(f"  Backend not available (no model loaded)")
            continue

        summary = BenchmarkSummary(backend=backend_name)

        for segment in segments:
            # Warmup runs
            for _ in range(args.warmup):
                run_benchmark(backend, segment, warmup=True)

            # Actual benchmark runs
            for run_idx in range(args.runs):
                result = run_benchmark(backend, segment, warmup=False)
                summary.runs.append(result)

                print(
                    f"  Run {run_idx + 1}: "
                    f"RTF={result.rtf:.3f}, "
                    f"latency={result.transcription_time_s:.3f}s, "
                    f"text='{result.text[:50]}...'" if len(result.text) > 50 else f"text='{result.text}'"
                )

        print_summary(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())
