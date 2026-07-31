# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Voxink.

Builds a standalone application that includes Python, all dependencies,
and the application code. Users don't need Python installed.

Usage:
    pip install pyinstaller
    pyinstaller build.spec

Output:
    dist/Voxink.app   (macOS)
    dist/voxink.exe   (Windows)
"""

import sys
from pathlib import Path
import importlib.util

block_cipher = None

# Find faster_whisper assets (VAD model) to include in the bundle
_fw_spec = importlib.util.find_spec('faster_whisper')
_fw_assets = []
if _fw_spec and _fw_spec.origin:
    _fw_dir = Path(_fw_spec.origin).parent
    _assets_dir = _fw_dir / 'assets'
    if _assets_dir.exists():
        _fw_assets = [(str(_assets_dir), 'faster_whisper/assets')]

a = Analysis(
    ['src/voxink/main.py'],
    pathex=[],
    binaries=[],
    datas=_fw_assets,
    hiddenimports=[
        'faster_whisper',
        'faster_whisper.vad',
        'ctranslate2',
        'onnxruntime',
        'sounddevice',
        'soundfile',
        'numpy',
        'pystray',
        'PIL',
        'click',
        # Platform-specific backends for pystray
        'pystray._darwin' if sys.platform == 'darwin' else 'pystray._win32',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='voxink',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window — tray app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico' if sys.platform == 'win32' else 'assets/icon.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='voxink',
)

# macOS: create .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Voxink.app',
        icon='assets/icon.icns',
        bundle_identifier='com.voxink.app',
        info_plist={
            'CFBundleName': 'Voxink',
            'CFBundleDisplayName': 'Voxink',
            'CFBundleShortVersionString': '0.1.0',
            'LSUIElement': True,  # Menu bar app, no dock icon
            'NSMicrophoneUsageDescription': 'Voxink needs microphone access to record meetings.',
            'NSSystemAudioRecordingUsageDescription': 'Voxink needs system audio access to record meeting participants.',
        },
    )
