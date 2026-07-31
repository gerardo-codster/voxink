"""CLI interface for voxink.

Commands:
    tray       Run as system tray icon (default — start/stop from menu)
    record     Start recording (Ctrl+C to stop)
    transcribe Transcribe a specific session or all pending
    devices    List available audio devices
    doctor     Check system readiness
"""

from __future__ import annotations

import signal
import sys
import time

import click

from voxink import __version__, config


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="voxink")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Local meeting recorder + transcriber with Spanish support.

    Records mic and system audio as two separate tracks, then transcribes
    on-device. Nothing ever leaves the machine.

    Run without arguments to launch the system tray icon.
    """
    if ctx.invoked_subcommand is None:
        # Default: launch tray mode
        ctx.invoke(tray)


@main.command()
@click.option("--out", type=click.Path(), default=None, help="Recordings root directory.")
@click.option(
    "--device",
    type=str,
    default=None,
    help="System audio device name or index (auto-detected if omitted).",
)
@click.option(
    "--language", "-l", type=str, default=None, help="Transcription language (default: from config or 'es')."
)
@click.option(
    "--model", "-m",
    type=click.Choice(["tiny", "base", "small", "medium", "large-v3"]),
    default=None,
    help="Whisper model size (default: from config or 'small'). Can also change from the tray menu.",
)
def tray(out: str | None, device: str | None, language: str | None, model: str | None) -> None:
    """Run as a system tray icon (default). Start/stop recording from the menu."""
    from pathlib import Path

    from voxink.tray import run_tray

    root = config.recordings_dir(out) if out else None

    # Parse device as int if it looks like a number
    dev: int | str | None = None
    if device is not None:
        try:
            dev = int(device)
        except ValueError:
            dev = device

    run_tray(recordings_root=root, system_device=dev, language=language, model=model)


@main.command()
@click.option("--out", type=click.Path(), default=None, help="Recordings root directory.")
@click.option(
    "--device",
    type=str,
    default=None,
    help="System audio device name or index (auto-detected if omitted).",
)
@click.option(
    "--language", "-l", type=str, default=None, help="Transcription language (default: from config or 'es')."
)
@click.option("--no-transcribe", is_flag=True, help="Skip automatic transcription after recording.")
def record(out: str | None, device: str | None, language: str | None, no_transcribe: bool) -> None:
    """Start recording mic + system audio. Press Ctrl+C to stop."""
    from voxink.session import RecordingSession
    from voxink.transcription.coordinator import transcribe_session

    root = config.recordings_dir(out)
    root.mkdir(parents=True, exist_ok=True)

    # Parse device as int if it looks like a number
    dev: int | str | None = None
    if device is not None:
        try:
            dev = int(device)
        except ValueError:
            dev = device

    session = RecordingSession(root=root, system_device=dev)

    # Handle Ctrl+C gracefully
    stop_requested = False

    def _signal_handler(signum: int, frame: object) -> None:
        nonlocal stop_requested
        if stop_requested:
            sys.exit(1)
        stop_requested = True
        click.echo("\n⏹ stopping recording...", err=True)

    signal.signal(signal.SIGINT, _signal_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _signal_handler)

    try:
        session.start()
    except RuntimeError as exc:
        click.echo(f"error: {exc}", err=True)
        raise SystemExit(1) from exc

    click.echo("● recording — press Ctrl+C to stop", err=True)
    start_time = time.time()

    # Wait until Ctrl+C
    try:
        while not stop_requested:
            elapsed = int(time.time() - start_time)
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            if h:
                ts = f"{h}:{m:02d}:{s:02d}"
            else:
                ts = f"{m}:{s:02d}"
            click.echo(f"\r● {ts}", nl=False, err=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    session.stop()
    click.echo("", err=True)

    # Transcribe if enabled
    if not no_transcribe and config.transcription_enabled():
        click.echo("transcribing...", err=True)
        lang = language or config.language()
        try:
            transcribe_session(session.dir, language=lang)
            click.echo(f"✓ transcript ready → {session.dir / 'transcript.md'}", err=True)
        except Exception as exc:
            click.echo(f"transcription failed: {exc}", err=True)
    else:
        click.echo(f"session saved → {session.dir}", err=True)


@main.command()
@click.argument("session_dir", type=click.Path(exists=True), required=False)
@click.option("--out", type=click.Path(), default=None, help="Recordings root (to find pending).")
@click.option("--language", "-l", type=str, default=None, help="Transcription language.")
@click.option("--all-pending", is_flag=True, help="Transcribe all pending sessions.")
def transcribe(session_dir: str | None, out: str | None, language: str | None, all_pending: bool) -> None:
    """Transcribe a session or all pending sessions."""
    from pathlib import Path

    from voxink.transcription.coordinator import resume_pending, transcribe_session

    lang = language or config.language()

    if session_dir:
        path = Path(session_dir)
        click.echo(f"transcribing {path.name}...", err=True)
        transcribe_session(path, language=lang)
        click.echo("✓ done", err=True)
    elif all_pending:
        root = config.recordings_dir(out)
        pending = resume_pending(root)
        if not pending:
            click.echo("no pending sessions found", err=True)
            return
        click.echo(f"found {len(pending)} pending session(s)", err=True)
        for p in pending:
            click.echo(f"\ntranscribing {p.name}...", err=True)
            try:
                transcribe_session(p, language=lang)
            except Exception as exc:
                click.echo(f"  failed: {exc}", err=True)
        click.echo("\n✓ all done", err=True)
    else:
        click.echo("specify a session directory or use --all-pending", err=True)
        raise SystemExit(1)


@main.command()
def devices() -> None:
    """List available audio input devices."""
    import sounddevice as sd

    devices_list = sd.query_devices()
    host_apis = sd.query_hostapis()

    click.echo("Audio devices:\n")
    click.echo(f"  {'#':<4} {'Name':<45} {'In Ch':<7} {'API'}")
    click.echo(f"  {'─'*4} {'─'*45} {'─'*7} {'─'*20}")

    for i, dev in enumerate(devices_list):
        if dev["max_input_channels"] > 0:
            api_name = host_apis[dev["hostapi"]]["name"] if dev["hostapi"] < len(host_apis) else "?"
            click.echo(
                f"  {i:<4} {dev['name']:<45} {dev['max_input_channels']:<7} {api_name}"
            )

    click.echo("")

    # Show auto-detected loopback
    from voxink.audio.system import find_loopback_device

    loopback = find_loopback_device()
    if loopback:
        click.echo(f"  Auto-detected system audio: #{loopback['index']} {loopback['name']}")
    else:
        click.echo("  ⚠ No system audio loopback device detected.")
        if sys.platform == "darwin":
            click.echo("    Install BlackHole: brew install blackhole-2ch")
            click.echo("    Then configure a Multi-Output Device in Audio MIDI Setup.")
        elif sys.platform == "win32":
            click.echo("    WASAPI loopback should be auto-detected. Check your audio drivers.")


@main.command()
@click.option("--out", type=click.Path(), default=None, help="Recordings root directory.")
def doctor(out: str | None) -> None:
    """Check system readiness: audio devices, dependencies, disk space."""
    import shutil

    import sounddevice as sd

    from voxink.audio.system import find_loopback_device

    root = config.recordings_dir(out)
    checks: list[tuple[str, str, str]] = []  # (status, name, detail)

    # Check mic
    try:
        default_input = sd.query_devices(kind="input")
        checks.append(("✓", "microphone", f"{default_input['name']}"))
    except Exception:
        checks.append(("✗", "microphone", "no input device found"))

    # Check system audio
    loopback = find_loopback_device()
    if loopback:
        checks.append(("✓", "system audio", f"{loopback['name']} ({loopback['method']})"))
    else:
        if sys.platform == "darwin":
            checks.append(("!", "system audio", "no loopback device — install blackhole-2ch"))
        elif sys.platform == "win32":
            checks.append(("!", "system audio", "no WASAPI loopback detected"))
        else:
            checks.append(("!", "system audio", "no loopback device found"))

    # Check recordings dir
    try:
        root.mkdir(parents=True, exist_ok=True)
        if root.exists() and root.is_dir():
            free = shutil.disk_usage(root).free / (1024**3)
            checks.append(("✓", "recordings folder", f"{root} ({free:.1f} GB free)"))
        else:
            checks.append(("✗", "recordings folder", f"can't create {root}"))
    except Exception as exc:
        checks.append(("✗", "recordings folder", f"{exc}"))

    # Check faster-whisper
    try:
        from faster_whisper import WhisperModel  # noqa: F401
        checks.append(("✓", "faster-whisper", "installed"))
    except ImportError:
        checks.append(("✗", "faster-whisper", "not installed — pip install faster-whisper"))

    # Check model cache
    model = config.transcription_model()
    from pathlib import Path as P

    cache_dir = P.home() / ".cache" / "huggingface" / "hub"
    model_dirs = list(cache_dir.glob(f"*whisper-{model}*")) if cache_dir.exists() else []
    if model_dirs:
        checks.append(("✓", "transcription model", f"{model} cached"))
    else:
        checks.append(("!", "transcription model", f"{model} not cached — downloads on first use (~3 GB)"))

    # Check config
    cfg_path = config.config_path()
    if cfg_path.exists():
        checks.append(("✓", "config", str(cfg_path)))
    else:
        checks.append(("!", "config", f"no config file (defaults apply) — {cfg_path}"))

    # Print results
    click.echo("")
    all_ok = True
    for status, name, detail in checks:
        click.echo(f"  {status} {name}: {detail}")
        if status == "✗":
            all_ok = False
    click.echo("")

    if all_ok:
        click.echo("  ready to record")
    else:
        click.echo("  some checks failed — fix the issues above")
        raise SystemExit(1)


@main.command()
@click.option("--out", type=click.Path(), default=None, help="Recordings root directory.")
def sessions(out: str | None) -> None:
    """List recorded sessions."""
    root = config.recordings_dir(out)
    if not root.exists():
        click.echo("no recordings found", err=True)
        return

    entries = sorted(root.iterdir())
    if not entries:
        click.echo("no sessions found", err=True)
        return

    for entry in entries:
        if entry.is_dir():
            meta_file = entry / "meta.json"
            transcript_file = entry / "transcript.json"

            status = "○"
            extra = ""
            if transcript_file.exists():
                status = "✓"
                extra = " [transcribed]"
            elif meta_file.exists():
                status = "◐"
                extra = " [pending transcription]"

            if meta_file.exists():
                import json

                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                duration = meta.get("duration_seconds", 0)
                m, s = divmod(duration, 60)
                extra += f" ({m}:{s:02d})"

            click.echo(f"  {status} {entry.name}{extra}")


if __name__ == "__main__":
    main()
