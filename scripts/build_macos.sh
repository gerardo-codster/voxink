#!/bin/bash
# Build Voxink as a standalone .app for macOS
# Run this from the project root: ./scripts/build_macos.sh
#
# Prerequisites (dev machine only, NOT needed by end users):
#   - Python 3.10+
#   - pip install -e .[build]

set -e

echo "=== Building Voxink for macOS ==="

cd "$(dirname "$0")/.."

echo "Installing build dependencies..."
pip install -e .[build]

echo "Building app bundle..."
pyinstaller build.spec --clean --noconfirm

echo ""
echo "=== Build complete ==="
echo "Output: dist/Voxink.app"
echo ""
echo "To distribute:"
echo "  1. Copy 'dist/Voxink.app' to /Applications (or zip it for users)"
echo "  2. Users just double-click it — no Python needed"
echo ""
