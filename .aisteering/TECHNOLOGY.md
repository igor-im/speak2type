# Technology Stack

## Languages & Frameworks

- **Python 3.11+**: Primary language (matches Fedora upstream)
- **PyGObject (GI)**: Python bindings for GTK, GLib, GStreamer, IBus
- **GTK4 / libadwaita**: Settings UI (upstream already uses this)

## Dependencies

### Core Runtime
- **IBus 1.5+**: Input method framework
- **GStreamer 1.0**: Audio capture pipeline
- **GLib / GObject**: Event loop, signals, settings

### Audio Capture
- **pipewiresrc**: Preferred audio source (native PipeWire)
- **pulsesrc**: Fallback audio source (works via pipewire-pulse)
- **webrtcdsp**: Optional noise suppression

### Speech Recognition Backends

| Backend | Library | Use Case |
|---------|---------|----------|
| Vosk | gst-vosk | Lightweight, streaming, offline |
| Whisper.cpp | pywhispercpp | Higher quality, offline |
| Parakeet | onnx-asr, onnxruntime | High performance, CPU-friendly |
| HTTP | requests/httpx | Remote/cloud services |

### Model Management
- **huggingface_hub**: Model downloads (Whisper, Parakeet)
- **XDG directories**: Standard Linux paths

## Development Tools

### Build & Package
- **pyproject.toml**: Modern Python packaging
- **meson**: Build system (from upstream, for data files)

### Testing
- **pytest**: Test framework
- **pytest-asyncio**: Async test support
- **hypothesis**: Property-based testing
- **schemathesis**: OpenAPI contract testing

### Code Quality
- **ruff**: Linting and formatting
- **mypy**: Type checking
- **pre-commit**: Git hooks

## Infrastructure

### Desktop Integration
- **GSettings**: Configuration storage
- **D-Bus**: Inter-process communication (IBus)
- **XDG Base Directories**: Standard paths for data/cache/config

### Audio
- **PipeWire**: Modern Linux audio server
- **PulseAudio**: Compatibility layer

## Platform Requirements

- **Primary**: Ubuntu 25.10+ (or equivalent with Python 3.11+, GTK4, IBus)
- **Also tested**: Fedora 43+ (upstream source)
- **Display server**: X11 and Wayland supported via IBus
