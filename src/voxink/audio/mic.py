"""Microphone recorder — captures the default input device to a WAV file.

Uses sounddevice for cross-platform audio capture. Streams buffers directly
to disk via soundfile so memory usage stays constant regardless of session
length.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


class MicRecorder:
    """Records the default input device to a WAV file."""

    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._file: sf.SoundFile | None = None
        self._recording = False
        self._lock = threading.Lock()
        self.first_buffer_at: datetime | None = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self, output_path: Path, samplerate: int = 44100, channels: int = 1) -> None:
        """Start capturing the microphone to `output_path` (WAV)."""
        if self._recording:
            return

        self._file = sf.SoundFile(
            str(output_path),
            mode="w",
            samplerate=samplerate,
            channels=channels,
            subtype="PCM_16",
        )
        self.first_buffer_at = None

        def _callback(indata: np.ndarray, frames: int, time_info: object, status: object) -> None:
            if status:
                print(f"mic: {status}", file=sys.stderr)
            with self._lock:
                if self._file is not None and self._recording:
                    if self.first_buffer_at is None:
                        self.first_buffer_at = datetime.now(timezone.utc)
                    self._file.write(indata.copy())

        self._stream = sd.InputStream(
            samplerate=samplerate,
            channels=channels,
            dtype="int16",
            callback=_callback,
            blocksize=4096,
        )
        self._recording = True
        self._stream.start()
        print(f"mic: recording → {output_path.name}", file=sys.stderr)

    def stop(self) -> None:
        """Stop capturing and close the file. Idempotent."""
        if not self._recording:
            return
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
