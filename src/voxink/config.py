"""User configuration for voxink.

Config file: ~/.config/voxink/config.json

Example:
{
    "recordings_dir": "~/Recordings",
    "language": "es",
    "transcription": {"enabled": true, "model": "small"},
    "on_stop": "my-hook"
}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _config_path() -> Path:
    """Platform-appropriate config file location."""
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Roaming" / "voxink"
    else:
        base = Path.home() / ".config" / "voxink"
    return base / "config.json"


def _load() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"warning: {path} is not valid JSON — ignoring config ({exc})", file=sys.stderr)
        return {}


def recordings_dir(cli_override: str | None = None) -> Path:
    """Resolve the recordings root: CLI flag > config > ~/Recordings."""
    if cli_override:
        return Path(cli_override).expanduser().resolve()
    configured = _load().get("recordings_dir")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / "Recordings"


def language() -> str:
    """Target transcription language. Default: Spanish."""
    return _load().get("language", "es")


def transcription_enabled() -> bool:
    """Whether automatic transcription runs after recording."""
    t = _load().get("transcription", {})
    return t.get("enabled", True) if isinstance(t, dict) else True


def transcription_model() -> str:
    """Whisper model size. Default: small (good balance of speed and quality)."""
    t = _load().get("transcription", {})
    return t.get("model", "small") if isinstance(t, dict) else "small"


def on_stop_hook() -> str | None:
    """Shell command to run after session finishes (transcript written)."""
    cmd = _load().get("on_stop")
    return cmd if isinstance(cmd, str) and cmd.strip() else None


def config_path() -> Path:
    """Return the config file path (for doctor/diagnostics)."""
    return _config_path()
