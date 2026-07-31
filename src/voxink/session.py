"""Recording session management.

A session is a timestamped folder containing two audio tracks (mic + system),
metadata, and (after transcription) the transcript files.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from voxink.audio import MicRecorder, SystemAudioRecorder


class RecordingSession:
    """One meeting recording: a timestamped folder with mic and system tracks."""

    def __init__(self, root: Path, system_device: int | str | None = None, mic_enabled: bool = True) -> None:
        """Create a session folder under `root` (yyyy.MM.dd-HHmm).

        Args:
            root: Parent directory for recordings.
            system_device: System audio device index or name.
            mic_enabled: Whether to record the microphone. If False, only system audio is captured.
        """
        self.started_at = datetime.now(timezone.utc)
        self.root = root
        self._mic_enabled = mic_enabled

        base = self.started_at.strftime("%Y.%m.%d-%H%M")
        candidate = root / base
        n = 2
        while candidate.exists():
            candidate = root / f"{base}-{n}"
            n += 1
        candidate.mkdir(parents=True, exist_ok=True)
        self.dir = candidate

        self._mic = MicRecorder()
        self._system = SystemAudioRecorder()
        self._system_device = system_device
        self._stopped = False

    def start(self) -> None:
        """Start recording tracks (system always, mic if enabled)."""
        system_path = self.dir / "system.wav"

        # Start system audio
        try:
            self._system.start(system_path, device=self._system_device)
        except RuntimeError as exc:
            print(f"warning: system audio unavailable: {exc}", file=sys.stderr)
            if not self._mic_enabled:
                raise RuntimeError(f"System audio failed and mic is disabled: {exc}") from exc
            print("recording mic only", file=sys.stderr)

        # Start mic if enabled
        if self._mic_enabled:
            mic_path = self.dir / "mic.wav"
            try:
                self._mic.start(mic_path)
            except Exception as exc:
                self._system.stop()
                raise RuntimeError(f"Mic recording failed: {exc}") from exc

        mode = "mic + system" if self._mic_enabled else "system only"
        print(f"● recording ({mode}) → {self.dir}", file=sys.stderr)

    def stop(self) -> None:
        """Stop both tracks and write meta.json."""
        if self._stopped:
            return
        self._stopped = True

        self._mic.stop()
        self._system.stop()

        ended = datetime.now(timezone.utc)

        # Compute offsets — how far each track lags behind the earliest
        mic_start = self._mic.first_buffer_at or self.started_at
        system_start = self._system.first_buffer_at or self.started_at
        earliest = min(mic_start, system_start)

        meta = {
            "started": self.started_at.isoformat(),
            "ended": ended.isoformat(),
            "duration_seconds": int((ended - self.started_at).total_seconds()),
            "files": {},
            "start_offset_ms": {},
        }

        if self._mic.is_recording or self._mic.first_buffer_at is not None:
            meta["files"]["mic"] = "mic.wav"
            meta["start_offset_ms"]["mic"] = int(
                (mic_start - earliest).total_seconds() * 1000
            )

        if self._system.is_recording or self._system.first_buffer_at is not None:
            meta["files"]["system"] = "system.wav"
            meta["start_offset_ms"]["system"] = int(
                (system_start - earliest).total_seconds() * 1000
            )

        # Always write mic if file exists
        mic_file = self.dir / "mic.wav"
        if mic_file.exists() and mic_file.stat().st_size > 44:
            meta["files"]["mic"] = "mic.wav"

        system_file = self.dir / "system.wav"
        if system_file.exists() and system_file.stat().st_size > 44:
            meta["files"]["system"] = "system.wav"

        meta_path = self.dir / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

        elapsed = self._format_elapsed(ended - self.started_at)
        print(f"○ stopped · {elapsed} · {self.dir}", file=sys.stderr)

    @staticmethod
    def _format_elapsed(td) -> str:
        total = int(td.total_seconds())
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
