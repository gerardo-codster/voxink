"""Audio capture modules for mic and system audio."""

from voxink.audio.mic import MicRecorder
from voxink.audio.system import SystemAudioRecorder

__all__ = ["MicRecorder", "SystemAudioRecorder"]
