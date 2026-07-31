"""System audio recorder — captures desktop/system audio output.

Cross-platform approach:
- macOS: Uses a loopback device (BlackHole, Soundflower) or screen capture.
         With sounddevice, you select the loopback device as input.
- Windows: Uses WASAPI loopback via sounddevice. Windows natively supports
           recording "what you hear" via loopback capture on output devices.

The user must configure the loopback device via config or the recorder
auto-detects a suitable device.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


def find_loopback_device() -> dict | None:
    """Find a suitable loopback/system audio device.

    Windows: Look for a WASAPI loopback device (output device used as input).
    macOS: Look for virtual audio devices like BlackHole, Soundflower, or
           any device with 'loopback' in the name.
    """
    devices = sd.query_devices()
    host_apis = sd.query_hostapis()

    # On Windows, find WASAPI host API and use output device as loopback
    if sys.platform == "win32":
        wasapi_idx = None
        for i, api in enumerate(host_apis):
            if "WASAPI" in api["name"]:
                wasapi_idx = i
                break
        if wasapi_idx is not None:
            # The default output device under WASAPI can be opened as loopback
            default_output = host_apis[wasapi_idx].get("default_output_device")
            if default_output is not None and default_output >= 0:
                dev = devices[default_output]
                return {"index": default_output, "name": dev["name"], "method": "wasapi_loopback"}

    # On macOS, look for virtual audio devices
    loopback_names = ["blackhole", "soundflower", "loopback", "virtual"]
    for i, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            name_lower = dev["name"].lower()
            if any(kw in name_lower for kw in loopback_names):
                return {"index": i, "name": dev["name"], "method": "virtual_device"}

    return None


class SystemAudioRecorder:
    """Records system/desktop audio to a WAV file.

    On Windows uses WASAPI loopback. On macOS requires a virtual audio device
    (BlackHole 2ch recommended — free, open source, zero latency).
    """

    def __init__(self) -> None:
        self._stream: sd.InputStream | None = None
        self._file: sf.SoundFile | None = None
        self._recording = False
        self._lock = threading.Lock()
        self.first_buffer_at: datetime | None = None
        self._device_info: dict | None = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def device_name(self) -> str | None:
        return self._device_info["name"] if self._device_info else None

    def start(
        self,
        output_path: Path,
        samplerate: int = 44100,
        channels: int = 2,
        device: int | str | None = None,
    ) -> None:
        """Start capturing system audio to `output_path` (WAV).

        Args:
            output_path: Where to write the WAV file.
            samplerate: Sample rate (default 44100).
            channels: Number of channels (default 2 for stereo).
            device: Specific device index or name. If None, auto-detects.
        """
        if self._recording:
            return

        # Resolve device
        if device is not None:
            if isinstance(device, str):
                # Search by name
                devices = sd.query_devices()
                for i, d in enumerate(devices):
                    if device.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                        self._device_info = {"index": i, "name": d["name"], "method": "manual"}
                        break
                else:
                    raise RuntimeError(
                        f"No input device matching '{device}' found. "
                        f"Run 'voxink devices' to list available devices."
                    )
            else:
                dev = sd.query_devices(device)
                self._device_info = {"index": device, "name": dev["name"], "method": "manual"}
        else:
            self._device_info = find_loopback_device()
            if self._device_info is None:
                raise RuntimeError(
                    "No loopback/system audio device found.\n"
                    "  macOS: Install BlackHole (brew install blackhole-2ch) and set it as "
                    "a Multi-Output Device in Audio MIDI Setup.\n"
                    "  Windows: WASAPI loopback should be detected automatically.\n"
                    "  Run 'voxink devices' to see available devices."
                )

        device_idx = self._device_info["index"]
        actual_dev = sd.query_devices(device_idx)
        max_ch = int(actual_dev["max_input_channels"])
        channels = min(channels, max_ch)

        # On Windows with WASAPI loopback, we need to match the device's default samplerate
        if sys.platform == "win32" and self._device_info.get("method") == "wasapi_loopback":
            device_sr = int(actual_dev["default_samplerate"])
            if device_sr > 0:
                samplerate = device_sr

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
                print(f"system: {status}", file=sys.stderr)
            with self._lock:
                if self._file is not None and self._recording:
                    if self.first_buffer_at is None:
                        self.first_buffer_at = datetime.now(timezone.utc)
                    self._file.write(indata.copy())

        extra_settings = None
        # On Windows, enable WASAPI loopback mode
        if sys.platform == "win32" and self._device_info.get("method") == "wasapi_loopback":
            try:
                extra_settings = sd.WasapiSettings(exclusive=False)
            except AttributeError:
                pass  # Older sounddevice without WasapiSettings

        kwargs: dict = {
            "samplerate": samplerate,
            "channels": channels,
            "dtype": "int16",
            "device": device_idx,
            "callback": _callback,
            "blocksize": 4096,
        }
        if extra_settings is not None:
            kwargs["extra_settings"] = extra_settings

        self._stream = sd.InputStream(**kwargs)
        self._recording = True
        self._stream.start()
        print(
            f"system: recording → {output_path.name} (device: {self._device_info['name']})",
            file=sys.stderr,
        )

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
