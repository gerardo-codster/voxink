#!/bin/bash
# Create a GitHub release with the macOS .app attached.
# Run after: gh auth login
# Usage: ./scripts/create_release.sh

set -e

cd "$(dirname "$0")/.."

VERSION="v0.1.0"
ZIP_FILE="dist/Voxink-macOS.zip"

if [ ! -f "$ZIP_FILE" ]; then
    echo "Error: $ZIP_FILE not found. Build first with: pyinstaller build.spec --clean --noconfirm"
    exit 1
fi

echo "Creating GitHub release $VERSION..."

gh release create "$VERSION" \
    --title "Voxink $VERSION" \
    --notes "## Voxink $VERSION — Initial Release

### Para usuarios (no necesitas instalar nada)

**macOS:** Descarga \`Voxink-macOS.zip\`, descomprime, arrastra \`Voxink.app\` a Aplicaciones, doble-click.

**Windows:** Próximamente (compila desde código con \`pyinstaller build.spec\`).

### Qué incluye

- Graba micrófono + audio del sistema como tracks separados
- Transcripción automática en español (on-device, nada sale de tu máquina)
- Icono en barra de menú / bandeja del sistema
- Selector de modelo de transcripción (tiny → large-v3)
- Toggle de micrófono (graba solo audio del sistema si lo desactivas)
- Compatible macOS y Windows

### Instrucciones

1. Descomprime el .zip
2. Arrastra Voxink.app a /Aplicaciones
3. Doble-click para ejecutar
4. Acepta permiso de micrófono cuando macOS pregunte
5. Click en el icono de la barra de menú → Start recording
6. Para auto-inicio: System Settings → General → Login Items → agrega Voxink" \
    "$ZIP_FILE"

echo "✓ Release $VERSION created successfully"
echo "  https://github.com/gerardo-codster/voxink/releases/tag/$VERSION"
