# Upstream Source

This project is forked from Fedora's `ibus-speech-to-text` project.

## Source Repository

- **Repository**: https://github.com/Manish7093/IBus-Speech-To-Text
- **Commit Hash**: `323d909ec62c2568dd562f97c8a897bb5b06a81c`
- **Commit Message**: "Add missing re import"
- **Fork Date**: 2026-01-26

## Fedora Package

- **Package Name**: `ibus-speech-to-text`
- **Fedora Wiki**: https://fedoraproject.org/wiki/Changes/ibus-speech-to-text
- **Fedora Packages**: https://packages.fedoraproject.org/pkgs/ibus-speech-to-text/ibus-speech-to-text/

## File Layout

The upstream code is preserved in `src/upstream/` to maintain the original structure:

```
src/upstream/
├── main.py                    # Entry point
├── mainconfig.py              # Config dialog entry point
├── sttengine.py               # IBus engine implementation
├── sttenginefactory.py        # Engine factory
├── sttgstbase.py              # GStreamer base class
├── sttgstfactory.py           # GStreamer factory (backend selection)
├── sttgstvosk.py              # Vosk backend
├── sttgstwhisper.py           # Whisper.cpp backend
├── sttvoskmodel.py            # Vosk model management
├── sttvoskmodelmanagers.py    # Vosk model download/selection
├── sttwhispermodel.py         # Whisper model management
├── sttwhispermodelmanagers.py # Whisper model download/selection
├── sttsegmentprocess.py       # Text processing/formatting
├── sttcurrentlocale.py        # Locale management
├── sttutils.py.in             # Utility functions (template)
├── sttwordstodigits.py        # Number formatting
├── stt*.ui                    # GTK4/libadwaita UI files
└── stt*.py                    # Additional UI components
```

## License

The upstream code is licensed under GPL-3.0. See `COPYING` for details.

## Modifications

This fork extends the upstream code with:

1. **Push-to-talk mode** (Alt+Space hotkey)
2. **Backend interface** (pluggable backend system)
3. **Parakeet ONNX backend** (via onnx-asr)
4. **HTTP backend** (for remote/cloud services)
5. **Privacy controls** (password field detection)

See `CHANGELOG.md` for detailed modification history.
