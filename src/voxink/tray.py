"""System tray UI for voxink.

Provides a menu-bar icon (macOS) / system tray icon (Windows) to control
recording without the CLI. Start/stop recording, select transcription model,
view sessions and transcription progress, open the recordings folder, and quit.

Uses pystray for cross-platform tray support:
- macOS: NSStatusItem (menu bar)
- Windows: Shell_NotifyIcon (system tray)
- Linux: AppIndicator (if available)
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from voxink import config
from voxink.session import RecordingSession
from voxink.transcription.coordinator import transcribe_session


# Available whisper models — ordered smallest to largest
AVAILABLE_MODELS = [
    ("tiny", "~75 MB — rápido, calidad baja"),
    ("base", "~150 MB — rápido, calidad aceptable"),
    ("small", "~500 MB — medio, buena calidad"),
    ("medium", "~1.5 GB — lento, muy buena calidad"),
    ("large-v3", "~3 GB — más lento, calidad excelente"),
]

# Max sessions to show in the menu
MAX_SESSIONS_IN_MENU = 10


def _create_icon_image(
    recording: bool = False, transcribing: bool = False, size: int = 64
) -> Image.Image:
    """Create icon: grey=idle, red=recording, orange=transcribing."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if recording:
        # Red filled circle with white dot
        draw.ellipse([4, 4, size - 4, size - 4], fill=(220, 50, 50, 255))
        inner = size // 4
        draw.ellipse(
            [size // 2 - inner // 2, size // 2 - inner // 2,
             size // 2 + inner // 2, size // 2 + inner // 2],
            fill=(255, 255, 255, 255),
        )
    elif transcribing:
        # Orange circle with "T" text indicator
        draw.ellipse([4, 4, size - 4, size - 4], fill=(230, 150, 30, 255))
        # Simple "T" shape for "transcribing"
        cx, cy = size // 2, size // 2
        draw.rectangle([cx - 10, cy - 12, cx + 10, cy - 8], fill=(255, 255, 255, 255))
        draw.rectangle([cx - 2, cy - 8, cx + 2, cy + 12], fill=(255, 255, 255, 255))
    else:
        # Dark grey circle with mic indicator
        draw.ellipse([4, 4, size - 4, size - 4], fill=(80, 80, 80, 255), outline=(160, 160, 160, 255), width=2)
        cx, cy = size // 2, size // 2
        draw.ellipse([cx - 6, cy - 10, cx + 6, cy + 6], fill=(220, 220, 220, 255))
        draw.rectangle([cx - 2, cy + 4, cx + 2, cy + 14], fill=(220, 220, 220, 255))

    return img


def _get_session_info(session_dir: Path) -> dict:
    """Get info about a session for display in the menu."""
    meta_path = session_dir / "meta.json"
    transcript_path = session_dir / "transcript.json"
    transcribe_log = session_dir / "transcribe.log"

    info = {"name": session_dir.name, "path": session_dir, "status": "recorded"}

    # Determine status
    if transcript_path.exists():
        info["status"] = "transcribed"
        # Count segments
        try:
            data = json.loads(transcript_path.read_text(encoding="utf-8"))
            seg_count = len(data.get("segments", []))
            info["segments"] = seg_count
        except Exception:
            pass
    elif transcribe_log.exists():
        # Check if it's currently being processed (log exists but no transcript)
        log_content = transcribe_log.read_text(encoding="utf-8")
        if "done —" in log_content or "failed" in log_content:
            info["status"] = "failed"
        else:
            info["status"] = "processing"

    # Get duration from meta
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            duration = meta.get("duration_seconds", 0)
            m, s = divmod(duration, 60)
            info["duration"] = f"{m}:{s:02d}"
        except Exception:
            info["duration"] = "?"
    else:
        info["duration"] = "?"

    return info


class TrayApp:
    """System tray application controller."""

    def __init__(
        self,
        recordings_root: Path | None = None,
        system_device: str | int | None = None,
        language: str | None = None,
        model: str | None = None,
    ) -> None:
        self._root = recordings_root or config.recordings_dir()
        self._root.mkdir(parents=True, exist_ok=True)
        self._system_device = system_device
        self._language = language or config.language()
        self._model = model or config.transcription_model()

        self._session: RecordingSession | None = None
        self._recording = False
        self._transcribing = False
        self._transcribing_session: str = ""  # Name of session being transcribed
        self._mic_enabled = True  # Toggle: record mic or only system audio
        self._elapsed_str = ""
        self._transcription_status = ""
        self._ticker_thread: threading.Thread | None = None
        self._stop_ticker = threading.Event()

        self._icon: pystray.Icon | None = None

    def run(self) -> None:
        """Run the tray application (blocks until quit)."""
        self._icon = pystray.Icon(
            name="voxink",
            icon=_create_icon_image(recording=False),
            title="voxink",
            menu=self._build_menu(),
        )
        print(f"voxink tray running — model: {self._model}, language: {self._language}", file=sys.stderr)
        self._icon.run()

    def _build_menu(self) -> pystray.Menu:
        """Build the context menu."""
        return pystray.Menu(
            pystray.MenuItem(
                self._status_text,
                action=None,
                enabled=False,
            ),
            pystray.MenuItem(
                self._transcription_text,
                action=None,
                enabled=False,
                visible=self._has_transcription_status,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._toggle_text,
                self._toggle_recording,
                default=True,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Sessions",
                self._build_sessions_submenu,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                self._mic_text,
                self._toggle_mic,
                enabled=self._mic_toggle_enabled,
            ),
            pystray.MenuItem(
                "Model",
                pystray.Menu(
                    *[
                        pystray.MenuItem(
                            f"{'✓ ' if model_id == self._model else '  '}{model_id} ({desc})",
                            self._make_model_selector(model_id),
                            enabled=not self._transcribing,
                        )
                        for model_id, desc in AVAILABLE_MODELS
                    ]
                ),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Open recordings folder",
                self._open_folder,
            ),
            pystray.MenuItem(
                "Quit",
                self._quit,
            ),
        )

    def _build_sessions_submenu(self) -> pystray.Menu:
        """Build the sessions submenu dynamically with recent sessions."""
        sessions = self._get_recent_sessions()

        if not sessions:
            return pystray.Menu(
                pystray.MenuItem("No recordings yet", action=None, enabled=False),
            )

        items = []
        for info in sessions:
            # Status icon
            status = info["status"]
            if status == "transcribed":
                icon_str = "✓"
            elif status == "processing" or info["name"] == self._transcribing_session:
                icon_str = "⏳"
            elif status == "failed":
                icon_str = "✗"
            else:
                icon_str = "○"

            # Build label
            duration = info.get("duration", "?")
            segments = info.get("segments")
            label = f"{icon_str} {info['name']} ({duration})"
            if segments is not None:
                label += f" — {segments} segments"
            elif info["name"] == self._transcribing_session:
                label += " — transcribing..."

            items.append(
                pystray.MenuItem(
                    label,
                    self._make_session_opener(info["path"]),
                )
            )

        # Add separator and "Open all" at the bottom
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem("Open recordings folder", self._open_folder))

        return pystray.Menu(*items)

    def _get_recent_sessions(self) -> list[dict]:
        """Get the most recent sessions with their status."""
        if not self._root.exists():
            return []

        sessions = []
        try:
            entries = sorted(self._root.iterdir(), reverse=True)  # newest first
            for entry in entries:
                if entry.is_dir() and (entry / "meta.json").exists():
                    sessions.append(_get_session_info(entry))
                    if len(sessions) >= MAX_SESSIONS_IN_MENU:
                        break
        except OSError:
            pass

        return sessions

    def _make_session_opener(self, session_path: Path):
        """Create a callback to open a specific session folder."""
        def _open(icon: pystray.Icon, item: pystray.MenuItem) -> None:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(session_path)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", str(session_path)])
            else:
                subprocess.Popen(["xdg-open", str(session_path)])
        return _open

    # --- Dynamic menu text callbacks ---

    def _status_text(self, _item: pystray.MenuItem) -> str:
        if self._recording:
            return f"● Recording · {self._elapsed_str}"
        return f"Idle · model: {self._model}"

    def _toggle_text(self, _item: pystray.MenuItem) -> str:
        return "⏹ Stop recording" if self._recording else "● Start recording"

    def _transcription_text(self, _item: pystray.MenuItem) -> str:
        return self._transcription_status

    def _has_transcription_status(self, _item: pystray.MenuItem) -> bool:
        return bool(self._transcription_status)

    # --- Actions ---

    def _make_model_selector(self, model_id: str):
        """Create a callback to select a specific model."""
        def _select(icon: pystray.Icon, item: pystray.MenuItem) -> None:
            self._model = model_id
            print(f"model changed to: {model_id}", file=sys.stderr)
            self._update_icon()
        return _select

    def _toggle_mic(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """Toggle microphone recording on/off."""
        self._mic_enabled = not self._mic_enabled
        status = "enabled" if self._mic_enabled else "disabled"
        print(f"microphone: {status}", file=sys.stderr)
        self._update_icon()

    def _mic_text(self, _item: pystray.MenuItem) -> str:
        return f"{'✓' if self._mic_enabled else '  '} Microphone"

    def _mic_toggle_enabled(self, _item: pystray.MenuItem) -> bool:
        """Disable mic toggle while recording (can't change mid-session)."""
        return not self._recording

    def _toggle_recording(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        if self._recording:
            return

        try:
            self._session = RecordingSession(
                root=self._root,
                system_device=self._system_device,
                mic_enabled=self._mic_enabled,
            )
            self._session.start()
        except RuntimeError as exc:
            print(f"recording failed: {exc}", file=sys.stderr)
            self._session = None
            return

        self._recording = True
        self._elapsed_str = "0:00"
        self._update_icon()

        # Start elapsed timer thread
        self._stop_ticker.clear()
        self._ticker_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._ticker_thread.start()

    def _stop_recording(self) -> None:
        if not self._recording or self._session is None:
            return

        self._recording = False
        self._stop_ticker.set()

        self._session.stop()
        session_dir = self._session.dir
        self._session = None
        self._elapsed_str = ""
        self._update_icon()

        # Transcribe in background
        if config.transcription_enabled():
            self._transcribing = True
            self._transcribing_session = session_dir.name
            self._transcription_status = f"⏳ Transcribing {session_dir.name} ({self._model})..."
            self._update_icon()
            thread = threading.Thread(
                target=self._transcribe_background, args=(session_dir,), daemon=True
            )
            thread.start()

    def _transcribe_background(self, session_dir: Path) -> None:
        """Run transcription in a background thread."""
        try:
            transcribe_session(session_dir, language=self._language, model=self._model)
            self._transcription_status = f"✓ {session_dir.name} — transcription complete"
        except Exception as exc:
            self._transcription_status = f"✗ {session_dir.name} — failed: {exc}"
            print(f"transcription error: {exc}", file=sys.stderr)

        self._transcribing = False
        self._transcribing_session = ""
        self._update_icon()

        # Clear status after 15 seconds
        time.sleep(15)
        self._transcription_status = ""
        self._update_icon()

    def _open_folder(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(self._root)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(self._root)])
        else:
            subprocess.Popen(["xdg-open", str(self._root)])

    def _quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self._recording:
            self._stop_recording()
        icon.stop()

    # --- Internal ---

    def _tick_loop(self) -> None:
        """Update elapsed time every second while recording."""
        start = time.time()
        while not self._stop_ticker.is_set():
            elapsed = int(time.time() - start)
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            self._elapsed_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            self._update_icon()
            self._stop_ticker.wait(1)

    def _update_icon(self) -> None:
        """Refresh icon image and menu."""
        if self._icon is None:
            return
        self._icon.icon = _create_icon_image(
            recording=self._recording, transcribing=self._transcribing
        )
        self._icon.update_menu()


def run_tray(
    recordings_root: Path | None = None,
    system_device: str | int | None = None,
    language: str | None = None,
    model: str | None = None,
) -> None:
    """Entry point for the tray application."""
    app = TrayApp(
        recordings_root=recordings_root,
        system_device=system_device,
        language=language,
        model=model,
    )
    app.run()
