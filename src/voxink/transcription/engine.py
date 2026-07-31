"""Whisper transcription engine using faster-whisper.

faster-whisper is a CTranslate2-based reimplementation of Whisper that runs
4x faster than OpenAI's original with comparable accuracy. It supports all
Whisper languages including Spanish natively.

Models download once on first use (~3GB for large-v3) and are cached locally.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import soundfile as sf
from faster_whisper import WhisperModel


@dataclass
class TranscriptSegment:
    """One timed span of recognized speech."""

    start: float  # seconds from track start
    end: float  # seconds from track start
    text: str


# Progress callback signature: (percent: int, last_segment_end: float, total_duration: float)
ProgressCallback = Callable[[int, float, float], None]


class WhisperEngine:
    """On-device transcription via faster-whisper.

    Supports all Whisper languages. Default: Spanish (es).
    Models: tiny, base, small, medium, large-v2, large-v3.
    """

    def __init__(self, model_size: str = "large-v3", device: str = "auto") -> None:
        """Initialize the engine.

        Args:
            model_size: Whisper model size. large-v3 recommended for Spanish.
            device: "auto" (uses GPU if available), "cpu", or "cuda".
        """
        self.model_size = model_size
        self.device = device
        self._model: WhisperModel | None = None

    @property
    def name(self) -> str:
        return "whisper"

    @property
    def model(self) -> str:
        return self.model_size

    def prepare(self) -> None:
        """Load the model (downloads on first use). Call before transcribe."""
        if self._model is not None:
            return

        # Determine compute type based on device
        compute_type: str
        device = self.device

        if device == "auto":
            # Try CUDA first, fall back to CPU
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    compute_type = "float16"
                else:
                    device = "cpu"
                    compute_type = "int8"
            except ImportError:
                device = "cpu"
                compute_type = "int8"
        elif device == "cuda":
            compute_type = "float16"
        else:
            compute_type = "int8"

        print(
            f"transcription: loading {self.model_size} on {device} ({compute_type})",
            file=sys.stderr,
        )
        self._model = WhisperModel(
            self.model_size,
            device=device,
            compute_type=compute_type,
        )
        print("transcription: model ready", file=sys.stderr)

    def transcribe(
        self,
        audio_path: Path,
        language: str = "es",
        on_progress: ProgressCallback | None = None,
    ) -> list[TranscriptSegment]:
        """Transcribe an audio file, returning timed segments.

        Args:
            audio_path: Path to WAV file.
            language: Language code (default "es" for Spanish).
            on_progress: Optional callback called as transcription advances.
                         Receives (percent, last_end_seconds, total_seconds).

        Returns:
            List of TranscriptSegment with start/end times and text.
        """
        if self._model is None:
            raise RuntimeError("Engine not prepared. Call prepare() first.")

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Get audio duration for progress reporting
        total_duration = 0.0
        try:
            with sf.SoundFile(str(audio_path)) as f:
                total_duration = f.frames / f.samplerate
        except Exception:
            pass

        # Try with VAD filter first; if the VAD model file is missing
        # (common in PyInstaller builds), fall back to no VAD
        try:
            segments_iter, info = self._model.transcribe(
                str(audio_path),
                language=language,
                beam_size=5,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=200,
                ),
            )
            # Iterate with progress tracking
            segments_list = self._collect_with_progress(
                segments_iter, total_duration, on_progress
            )
        except Exception as vad_err:
            if "NO_SUCHFILE" in str(vad_err) or "silero_vad" in str(vad_err):
                print(
                    "transcription: VAD model unavailable, transcribing without VAD filter",
                    file=sys.stderr,
                )
                segments_iter, info = self._model.transcribe(
                    str(audio_path),
                    language=language,
                    beam_size=5,
                    word_timestamps=True,
                    vad_filter=False,
                )
                segments_list = self._collect_with_progress(
                    segments_iter, total_duration, on_progress
                )
            else:
                raise

        print(
            f"transcription: {audio_path.name} — detected language {info.language} "
            f"(probability {info.language_probability:.2f})",
            file=sys.stderr,
        )

        result: list[TranscriptSegment] = []
        for segment in segments_list:
            text = segment.text.strip()
            if text:
                result.append(TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=text,
                ))

        # Final progress
        if on_progress and total_duration > 0:
            on_progress(100, total_duration, total_duration)

        return result

    def _collect_with_progress(self, segments_iter, total_duration: float, on_progress):
        """Collect segments from iterator while reporting progress."""
        segments_list = []
        last_reported_pct = -1

        for segment in segments_iter:
            segments_list.append(segment)

            # Report progress based on how far into the audio we've reached
            if on_progress and total_duration > 0:
                pct = min(99, int((segment.end / total_duration) * 100))
                if pct > last_reported_pct:
                    last_reported_pct = pct
                    on_progress(pct, segment.end, total_duration)

        return segments_list

    def release(self) -> None:
        """Release model memory."""
        self._model = None
