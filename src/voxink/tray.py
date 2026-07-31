"""System tray UI for voxink.

Provides a menu-bar icon (macOS) / system tray icon (Windows) to control
recording without the CLI. Start/stop recording, select transcription model,
view conversations and transcription progress, reprocess transcriptions, and quit.

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

# Max conversations to show in the menu
MAX_CONVERSATIONS_IN_MENU = 10


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


def _get_conversation_info(session_dir: Path) -> dict:
    """Get info about a conversation for display in the menu."""
    meta_path = session_dir / "meta.json"
    transcript_path = session_dir / "transcript.json"
    transcribe_log = session_dir / "transcribe.log"

    info = {"name": session_dir.name, "path": session_dir, "status": "recorded"}

    # Determine status
    if transcript_path.exists():
        info["status"] = "transcribed"
        try:
            data = json.loads(transcript_path.read_text(encoding="utf-8"))
            info["segments"] = len(data.get("segments", []))
            info["model_used"] = data.get("model", "?")
        except Exception:
            pass
    elif transcribe_log.exists():
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
        self._transcribing_session: str = ""
        self._mic_enabled = True
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
        conversations_items = self._get_conversations_menu_items()

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
                "Recordings",
                pystray.Menu(*conversations_items),
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

    def _get_conversations_menu_items(self) -> list:
        """Build conversation menu items with submenus for each conversation."""
        conversations = self._get_recent_conversations()

        if not conversations:
            return [pystray.MenuItem("No recordings yet", action=None, enabled=False)]

        items = []
        for info in conversations:
            # Status icon
            status = info["status"]
            is_current = info["name"] == self._transcribing_session
            if is_current:
                icon_str = "⏳"
            elif status == "transcribed":
                icon_str = "✓"
            elif status == "processing":
                icon_str = "⏳"
            elif status == "failed":
                icon_str = "✗"
            else:
                icon_str = "○"

            # Build label
            duration = info.get("duration", "?")
            segments = info.get("segments")
            label = f"{icon_str} {info['name']} ({duration})"
            if is_current:
                label += " — transcribing..."
            elif segments is not None:
                model_used = info.get("model_used", "")
                label += f" — {segments} seg"
                if model_used:
                    label += f" [{model_used}]"

            # Each conversation gets a submenu with actions
            conv_submenu = self._build_conversation_submenu(info)
            items.append(
                pystray.MenuItem(label, pystray.Menu(*conv_submenu))
            )

        return items

    def _build_conversation_submenu(self, info: dict) -> list:
        """Build submenu for a single conversation: open folder, reprocess."""
        session_path = info["path"]
        status = info["status"]
        is_current = info["name"] == self._transcribing_session

        items = [
            pystray.MenuItem(
                "Open folder",
                self._make_session_opener(session_path),
            ),
        ]

        # Reprocess option — available if not currently transcribing this one
        can_reprocess = not is_current and not self._transcribing
        if status in ("transcribed", "failed", "processing", "recorded"):
            reprocess_label = f"Reprocess with {self._model}"
            items.append(
                pystray.MenuItem(
                    reprocess_label,
                    self._make_reprocess_action(session_path),
                    enabled=can_reprocess,
                ),
            )

        return items

    def _get_recent_conversations(self) -> list[dict]:
        """Get the most recent conversations with their status."""
        if not self._root.exists():
            return []

        conversations = []
        try:
            entries = sorted(self._root.iterdir(), reverse=True)  # newest first
            for entry in entries:
                if entry.is_dir() and (entry / "meta.json").exists():
                    conversations.append(_get_conversation_info(entry))
                    if len(conversations) >= MAX_CONVERSATIONS_IN_MENU:
                        break
        except OSError:
            pass

        return conversations

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

    def _make_reprocess_action(self, session_path: Path):
        """Create a callback to reprocess transcription for a conversation."""
        def _reprocess(icon: pystray.Icon, item: pystray.MenuItem) -> None:
            if self._transcribing:
                return  # Don't allow if already transcribing

            # Remove existing transcript so it gets reprocessed
            transcript_json = session_path / "transcript.json"
            transcript_md = session_path / "transcript.md"
            transcribe_log = session_path / "transcribe.log"

            for f in [transcript_json, transcript_md, transcribe_log]:
                if f.exists():
                    f.unlink()

            # Start transcription in background with current model
            self._transcribing = True
            self._transcribing_session = session_path.name
            self._transcription_status = f"⏳ Reprocessing {session_path.name} ({self._model})..."
            self._update_icon()

            thread = threading.Thread(
                target=self._transcribe_background, args=(session_path,), daemon=True
            )
            thread.start()
            print(f"reprocessing {session_path.name} with model {self._model}", file=sys.stderr)

        return _reprocess

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

    def _prompt_recording_name(self) -> str | None:
        """Show a native dialog asking for a recording name.

        Returns the name entered, or None if cancelled/empty (use default).
        macOS: uses osascript. Windows: uses a simple tkinter dialog.
        """
        if sys.platform == "darwin":
            script = (
                'set dialogResult to display dialog "Recording name (leave empty for default):" '
                'default answer "" with title "Voxink" '
                'buttons {"Cancel", "Start"} default button "Start"\n'
                'return text returned of dialogResult'
            )
            try:
                result = subprocess.run(
                    ["/usr/bin/osascript", "-e", script],
                    capture_output=True, text=True, timeout=60,
                )
                if result.returncode == 0:
                    name = result.stdout.strip()
                    return name if name else None
            except (subprocess.TimeoutExpired, Exception):
                pass
            return None
        elif sys.platform == "win32":
            try:
                import tkinter as tk
                from tkinter import simpledialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                name = simpledialog.askstring(
                    "Voxink", "Recording name (leave empty for default):", parent=root
                )
                root.destroy()
                return name if name and name.strip() else None
            except Exception:
                return None
        else:
            return None

    def _start_recording(self) -> None:
        if self._recording:
            return

        # Ask for a recording name (dialog). Empty/cancel = use default timestamp
        name = self._prompt_recording_name()

        try:
            self._session = RecordingSession(
                root=self._root,
                system_device=self._system_device,
                mic_enabled=self._mic_enabled,
                name=name,
            )
            self._session.start()
        except RuntimeError as exc:
            print(f"recording failed: {exc}", file=sys.stderr)
            self._session = None
            # Show error in the menu for the user to see
            self._transcription_status = f"✗ {exc}"
            self._update_icon()
            # Clear error after 10 seconds
            threading.Thread(target=self._clear_status_later, args=(10,), daemon=True).start()
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
            def _on_progress(pct: int, track_name: str) -> None:
                self._transcription_status = f"⏳ {session_dir.name} — {track_name} {pct}%"
                self._update_icon()

            transcribe_session(
                session_dir,
                language=self._language,
                model=self._model,
                on_progress=_on_progress,
            )
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

    def _clear_status_later(self, seconds: int) -> None:
        """Clear the transcription status after a delay."""
        time.sleep(seconds)
        self._transcription_status = ""
        self._update_icon()

    def _update_icon(self) -> None:
        """Refresh icon image and rebuild menu (so conversations list updates)."""
        if self._icon is None:
            return
        self._icon.icon = _create_icon_image(
            recording=self._recording, transcribing=self._transcribing
        )
        self._icon.menu = self._build_menu()
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
