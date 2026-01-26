# speak2type

Speech-to-text input method engine for Linux desktops (GNOME/IBus).

## Features

- **Push-to-talk dictation**: Hold Alt+Space to speak, release to transcribe
- **Multiple backends**: Vosk (lightweight), Whisper.cpp (quality), Parakeet (performance)
- **HTTP backend**: Connect to remote/cloud speech services
- **Privacy-first**: Automatically disabled in password fields
- **GNOME integration**: Native IBus engine with GTK4/libadwaita settings UI

## Requirements

- Ubuntu 25.10+ (or Fedora 43+)
- Python 3.11+
- IBus 1.5+
- GStreamer 1.0
- GTK4 / libadwaita

## Quick Start

```bash
# Install dependencies and set up the engine
./scripts/dev-install.sh

# Add to your shell profile (~/.bashrc):
export IBUS_COMPONENT_PATH="${HOME}/.local/share/ibus/component:${IBUS_COMPONENT_PATH:-/usr/share/ibus/component}"

# Restart your shell, then:
ibus restart

# Add "Speech To Text" input source in GNOME Settings
```

## Usage

1. Select "Speech To Text" as your input source
2. Focus any text field
3. Hold **Alt+Space** and speak
4. Release to transcribe and commit text

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src/

# Type checking
mypy src/
```

## License

GPL-3.0-or-later. See [COPYING](COPYING) for details.

Based on [ibus-speech-to-text](https://github.com/Manish7093/IBus-Speech-To-Text) from Fedora.
