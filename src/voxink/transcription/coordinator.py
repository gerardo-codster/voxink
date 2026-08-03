"""Transcription coordinator — processes recorded sessions.

Transcribes mic.wav as "me" and system.wav as "them", merges by timestamp,
and writes transcript.json + transcript.md. The filesystem is the queue:
a session with meta.json but no transcript.json is pending.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from voxink import config
from voxink.transcription.engine import TranscriptSegment, WhisperEngine


def transcribe_session(
    session_dir: Path,
    language: str | None = None,
    model: str | None = None,
    on_progress: callable | None = None,
) -> None:
    """Transcribe a single session directory.

    Reads meta.json to find tracks, transcribes each, merges by timestamp,
    writes transcript.json and transcript.md.

    Args:
        session_dir: Path to the session folder.
        language: Language code (default from config).
        model: Whisper model size (default from config).
        on_progress: Optional callback (percent, track_name) called during transcription.
    """
    lang = language or config.language()
    meta_path = session_dir / "meta.json"

    if not meta_path.exists():
        _log(session_dir, "no meta.json found — skipping")
        return

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    files = meta.get("files", {})
    offsets = meta.get("start_offset_ms", {})

    if not files:
        _log(session_dir, "no audio files in meta.json — skipping")
        return

    # Prepare the engine
    model_size = model or config.transcription_model()
    engine = WhisperEngine(model_size=model_size)
    engine.prepare()

    merged: list[dict] = []

    # Track mapping: filename → speaker label
    track_speakers = {"mic": "me", "system": "them"}

    for track_key, filename in files.items():
        audio_path = session_dir / filename
        if not audio_path.exists():
            _log(session_dir, f"skipping missing track {filename}")
            continue

        # Skip empty files (just the WAV header)
        if audio_path.stat().st_size <= 44:
            _log(session_dir, f"skipping empty track {filename}")
            continue

        # Skip silent files (pure zeros = no real audio captured)
        if _is_silent(audio_path):
            _log(session_dir, f"skipping silent track {filename} — no audio detected")
            continue

        speaker = track_speakers.get(track_key, track_key)
        _log(session_dir, f"transcribing {filename} ({engine.name}/{engine.model}) → {speaker}")

        def _track_progress(pct: int, pos: float, total: float) -> None:
            if on_progress:
                on_progress(pct, filename)

        try:
            segments = engine.transcribe(audio_path, language=lang, on_progress=_track_progress)
        except Exception as exc:
            _log(session_dir, f"failed to transcribe {filename}: {exc}")
            continue

        offset_s = offsets.get(track_key, 0) / 1000.0
        for seg in segments:
            merged.append({
                "speaker": speaker,
                "start_ms": int((seg.start + offset_s) * 1000),
                "end_ms": int((seg.end + offset_s) * 1000),
                "text": seg.text,
            })

    # Sort by start time
    merged.sort(key=lambda s: s["start_ms"])

    # Write transcript
    transcript = {
        "engine": engine.name,
        "model": engine.model,
        "language": lang,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "segments": merged,
    }

    transcript_json = session_dir / "transcript.json"
    transcript_json.write_text(
        json.dumps(transcript, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Write readable markdown
    transcript_md = session_dir / "transcript.md"
    transcript_md.write_text(
        _render_markdown(session_dir.name, transcript),
        encoding="utf-8",
    )

    engine.release()
    _log(session_dir, f"done — {len(merged)} segments")

    # Run on_stop hook
    hook = config.on_stop_hook()
    if hook:
        try:
            subprocess.Popen(
                [hook, str(session_dir)],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            _log(session_dir, f"on_stop hook failed: {exc}")


def resume_pending(root: Path) -> list[Path]:
    """Find sessions that have meta.json but no transcript.json (pending)."""
    if not root.exists():
        return []
    pending = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            meta = entry / "meta.json"
            transcript = entry / "transcript.json"
            if meta.exists() and not transcript.exists():
                pending.append(entry)
    return pending


def _render_markdown(title: str, transcript: dict) -> str:
    """Render transcript as readable markdown."""
    lines = [
        f"# {title}",
        "",
        f"engine: {transcript['engine']} ({transcript['model']})",
        f"language: {transcript['language']}",
        "",
    ]
    for seg in transcript["segments"]:
        clock = _format_clock(seg["start_ms"])
        lines.append(f"**[{clock}] {seg['speaker']}:** {seg['text']}")
        lines.append("")
    return "\n".join(lines)


def _format_clock(ms: int) -> str:
    """Format milliseconds as h:mm:ss or m:ss."""
    total = ms // 1000
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _log(session_dir: Path, message: str) -> None:
    """Append to session's transcribe.log and print to stderr."""
    line = f"{datetime.now(timezone.utc).isoformat()} {message}\n"
    print(f"  {message}", file=sys.stderr)
    log_path = session_dir / "transcribe.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def _is_silent(audio_path: Path, check_seconds: int = 10) -> bool:
    """Check if an audio file is pure silence (all zeros).

    Samples the beginning, middle, and end of the file.
    Returns True if all sampled sections are silent.
    """
    try:
        import numpy as np
        import soundfile as sf

        with sf.SoundFile(str(audio_path)) as f:
            if f.frames == 0:
                return True

            sr = f.samplerate
            samples_to_check = sr * check_seconds

            # Check beginning
            chunk = f.read(min(samples_to_check, f.frames))
            if np.any(chunk != 0):
                return False

            # Check middle
            if f.frames > samples_to_check * 3:
                f.seek(f.frames // 2)
                chunk = f.read(min(samples_to_check, f.frames - f.frames // 2))
                if np.any(chunk != 0):
                    return False

            # Check end
            if f.frames > samples_to_check * 2:
                f.seek(max(0, f.frames - samples_to_check))
                chunk = f.read(samples_to_check)
                if np.any(chunk != 0):
                    return False

            return True
    except Exception:
        return False
