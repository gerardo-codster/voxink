@echo off
REM Build Voxink as a standalone .exe for Windows
REM Run this from the project root: scripts\build_windows.bat
REM
REM Prerequisites (dev machine only, NOT needed by end users):
REM   - Python 3.10+
REM   - pip install -e .[build]

echo === Building Voxink for Windows ===

cd /d "%~dp0\.."

echo Installing build dependencies...
pip install -e .[build]
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    exit /b 1
)

echo Building executable...
pyinstaller build.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: Build failed
    exit /b 1
)

echo.
echo === Build complete ===
echo Output: dist\voxink.exe
echo.
echo To distribute: copy dist\voxink.exe to end users.
echo They just double-click it — no Python needed.
echo.
pause
