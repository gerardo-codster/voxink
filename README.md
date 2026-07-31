# Voxink

Grabador de reuniones local + transcripción automática en español. Graba el micrófono y el audio del sistema como dos tracks separados; cuando detienes la grabación, transcribe todo on-device y genera un transcript con marcas de tiempo y speaker tags (`me` / `them`). Nada sale de tu máquina.

## Instalación

### Para usuarios (sin conocimientos técnicos)

#### Windows
1. Descarga `VoxinkSetup.exe` del [último release](releases/)
2. Doble-click en el instalador → Siguiente → Siguiente → Instalar
3. Listo — aparece el icono en la bandeja del sistema (abajo a la derecha)
4. Se inicia automáticamente cada vez que enciendes la computadora

#### macOS
1. Descarga `Voxink.app.zip` del [último release](releases/)
2. Descomprime y arrastra `Voxink.app` a tu carpeta Aplicaciones
3. Doble-click para ejecutar
4. La primera vez macOS preguntará permisos de micrófono — acepta

> **Nota macOS:** Para grabar el audio del sistema (lo que dicen los demás en la reunión),
> necesitas instalar BlackHole. Pide ayuda a alguien técnico para configurarlo una vez,
> o usa solo la grabación de micrófono.

---

### Para desarrolladores (compilar desde código fuente)

#### macOS

```sh
# 1. Instalar dependencias del sistema
brew install portaudio

# 2. (Opcional) Instalar BlackHole para capturar audio del sistema
brew install blackhole-2ch

# 3. Clonar e instalar
cd voxink
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 4. Ejecutar
voxink          # lanza el tray
voxink record   # o desde CLI
```

#### Windows

```powershell
# 1. Clonar e instalar
cd voxink
python -m venv .venv && .venv\Scripts\activate
pip install -e .

# 2. Ejecutar
voxink          # lanza el tray
```

#### Compilar el instalador

```sh
# macOS — genera Voxink.app
pip install -e .[build]
pyinstaller build.spec --clean --noconfirm
# Output: dist/Voxink.app

# Windows — genera voxink.exe + instalador
pip install -e .[build]
pyinstaller build.spec --clean --noconfirm
# Luego con NSIS: makensis scripts\installer_windows.nsi
# Output: dist/VoxinkSetup.exe
```

## Uso

### Desde el icono (modo tray — por defecto)

Ejecuta `voxink` (o doble-click en la app). Aparece un icono en la barra de menú / bandeja del sistema:

- **Click → Start recording** — empieza a grabar, icono se pone rojo
- **Click → Stop recording** — detiene, transcribe automáticamente (icono naranja)
- **Model →** submenú para elegir modelo de transcripción
- **Open recordings folder** — abre la carpeta de sesiones
- **Quit** — cierra la app

Estados del icono:
- ⚫ Gris = idle
- 🔴 Rojo = grabando
- 🟠 Naranja = transcribiendo

### Desde CLI

```sh
# Grabar (Ctrl+C para detener)
voxink record

# Grabar sin transcripción automática
voxink record --no-transcribe

# Especificar dispositivo de audio del sistema
voxink record --device "BlackHole 2ch"

# Transcribir sesiones pendientes
voxink transcribe --all-pending

# Ver dispositivos de audio disponibles
voxink devices

# Verificar que el sistema está listo
voxink doctor

# Listar sesiones grabadas
voxink sessions
```

## Estructura de una sesión

Cada sesión crea una carpeta en `~/Recordings/<yyyy.MM.dd-HHmm>/`:

| Archivo | Contenido |
|---|---|
| `mic.wav` | Tu voz (dispositivo de entrada por defecto) |
| `system.wav` | Lo que reproduce tu Mac/PC — el otro lado de la llamada |
| `meta.json` | Timestamps de inicio/fin, duración, offsets por track |
| `transcript.json` | Transcript canónico — engine, modelo, segmentos con speaker tags |
| `transcript.md` | El mismo transcript renderizado para lectura |
| `transcribe.log` | Log de progreso/errores de transcripción |

## Transcripción

Motor: **faster-whisper** (Whisper de OpenAI optimizado con CTranslate2).

- Soporta español nativamente (y 90+ idiomas)
- ~4x más rápido que el Whisper original
- Modelos se descargan una vez en la primera transcripción
- Usa GPU (CUDA) si está disponible, CPU si no
- VAD (Voice Activity Detection) integrado para saltar silencios

### Modelos disponibles

| Modelo | Tamaño | Velocidad | Calidad español |
|--------|--------|-----------|-----------------|
| `tiny` | ~75 MB | Muy rápido | Baja |
| `base` | ~150 MB | Rápido | Aceptable |
| `small` | ~500 MB | Medio | Buena ← **default** |
| `medium` | ~1.5 GB | Lento | Muy buena |
| `large-v3` | ~3 GB | Más lento | Excelente |

Puedes cambiar el modelo desde el menú del tray o en la configuración.

## Configuración

Opcional, en `~/.config/voxink/config.json` (macOS/Linux) o
`%APPDATA%\voxink\config.json` (Windows):

```json
{
    "recordings_dir": "~/Recordings",
    "language": "es",
    "transcription": {
        "enabled": true,
        "model": "small"
    },
    "on_stop": "my-post-processing-script"
}
```

- `recordings_dir` — dónde guardar sesiones
- `language` — idioma para transcripción (default: `es`)
- `transcription.enabled` — `false` para solo grabar
- `transcription.model` — tamaño del modelo (ver tabla arriba)
- `on_stop` — comando shell que se ejecuta después de transcribir

## Capturas de audio del sistema

### macOS — BlackHole

BlackHole es un driver de audio virtual gratuito y open source. Al configurar un Multi-Output Device, el audio se envía simultáneamente a tus bocinas y a BlackHole, donde Voxink puede grabarlo.

### Windows — WASAPI Loopback

Windows permite nativamente grabar "lo que se escucha" vía WASAPI loopback. Voxink lo detecta automáticamente sin configuración adicional.
