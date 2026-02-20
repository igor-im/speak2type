# speak2type

`speak2type` is a speech-to-text input method engine for Linux desktops, built around IBus integration with a global push-to-talk workflow.
It supports both native IBus text input and non-IBus app workflows.

| :exclamation:  This is less than version 0, use at your own risk!   |
|----------------------------------------------|

## What it does

- **Push-to-talk dictation** (default: `Alt+Space`)
- **Two output modes with the same hotkey**:
  - **IBus/native apps**: transcription is committed in place at the current cursor/focus
  - **Non-IBus apps** (for example VS Code/Electron contexts): transcription is copied to clipboard
- **Parakeet backend** (local ONNX) as the currently working backend
- **Settings app** (GTK4 + libadwaita) to manage backend dependencies and models
- **Privacy safeguard (IBus-aware fields)**: recording is disabled for `PASSWORD`/`PIN` input purposes
- **Global hotkey support** via desktop portal listener

- Chrome (Native Ibus)
https://youtu.be/QUHK7w-qBb0

- VS Code (Electron, non-Ibus)
https://youtu.be/O3MZFxC4ipE

## Platform requirements

Minimum expected environment:

- Linux desktop using **IBus 1.5+**
- Python **3.11+**
- GStreamer 1.0
- GTK4 + libadwaita (for preferences UI)

Tested target distro in project docs/scripts:

- Ubuntu 25.10+

## Quick start (development install)

The repo includes a development installer that sets up system deps, Python env, IBus component files, and GSettings schema.

```bash
./scripts/dev-install.sh
```

Then ensure your shell exports `IBUS_COMPONENT_PATH` (if not already set):

```bash
export IBUS_COMPONENT_PATH="$HOME/.local/share/ibus/component:${IBUS_COMPONENT_PATH:-/usr/share/ibus/component}"
```

Restart your shell and IBus:

```bash
ibus restart
```

Finally add **Speech To Text** as an input source in GNOME Settings.

## Debian/Ubuntu package install (APT / .deb)

If you prefer a system package instead of the development installer, the repository includes Debian packaging files under `debian/`.

Build and install locally:

```bash
sudo apt-get update
sudo apt-get install -y debhelper dh-python pybuild-plugin-pyproject python3-all python3-build python3-pytest python3-setuptools python3-wheel
dpkg-buildpackage -us -uc -b
sudo apt-get install -y ../speak2type_0.1.0-1_all.deb
ibus restart
```

## GNOME Settings

For the best push-to-talk experience, adjust these settings in **GNOME Settings → Accessibility → Typing**:

- **Repeat Keys**: **Off** — prevents the PTT key from flooding spaces while held
- **Sticky Keys**: **On** — allows modifier+key combos to be registered cleanly by the portal

## Usage

1. Select "Speech To Text" as your input source
2. Focus any text field
3. Hold **Ctrl+Space** and speak
4. Release to transcribe and commit text
After install, add **Speech To Text** as an input source in GNOME Settings.

For detailed packaging steps, see `debian/README.build.md`.

## Usage

1. Select **Speech To Text** as your active input source.
2. Focus the target app/text field.
3. Hold the push-to-talk hotkey (default `Alt+Space`).
4. Speak.
5. Release the hotkey to transcribe.
6. Result handling:
   - In IBus-native input contexts: text is inserted at cursor/focus.
   - In non-IBus contexts (e.g. VS Code/Electron): text is copied to clipboard.

## Backend status

### Working

- **Parakeet**: fast local ONNX inference, model download supported in preferences.

### Experimental / not considered working yet

- Whisper.cpp
- Vosk (`gst-vosk`)
- HTTP backend (remote/self-hosted API path)

A reference FastAPI server for the HTTP path is provided in `server/main.py`:

```bash
uvicorn server.main:app --port 8000
```

Endpoints:

- `POST /transcribe` (generic)
- `POST /v1/audio/transcriptions` (OpenAI-compatible)

OpenAPI schema: `server/openapi.yaml`

## Development

Install editable package with dev extras:

```bash
pip install -e ".[dev]"
```

Useful commands:

```bash
pytest
ruff check src tests
mypy src
```

Run engine manually (outside IBus integration workflows):

```bash
python -m speak2type
```

## Repository layout

- `src/speak2type/` — current engine, backends, UI, and model management
- `server/` — reference HTTP transcription service + OpenAPI spec
- `tests/` — unit/integration tests
- `scripts/dev-install.sh` — Ubuntu-focused setup helper
- `src/upstream/` — upstream reference code retained for comparison/migration

## Known limitations

- Alpha quality; crashes/hangs can still occur in edge cases
- **Mic symbol may remain stuck as active in task bar** (likely GStreamer pipeline stuck in `PLAYING`)
- Some backend dependencies are large and may require manual system packages
- Vosk path depends on `gst-vosk`, which may not be packaged on all distros

## License

GPL-3.0-or-later. See [COPYING](COPYING).

## Credits

This project is based on [ibus-speech-to-text](https://github.com/Manish7093/IBus-Speech-To-Text) from Fedora and continues to evolve as a refactor/new implementation track.
