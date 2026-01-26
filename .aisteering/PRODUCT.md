# Product

## Purpose

speak2type is a speech-to-text input method engine for Linux desktops (GNOME/IBus). It allows users to dictate text into any application using voice, with support for multiple recognition backends and a push-to-talk activation model.

The project solves the problem of seamless voice input on Linux by:
- Integrating with the standard IBus input method framework
- Providing a simple push-to-talk interface (Alt+Space)
- Supporting multiple local and remote speech recognition engines
- Prioritizing privacy with password field detection

## Target Users

1. **Desktop Linux users** who want voice dictation similar to macOS/Windows built-in dictation
2. **Accessibility users** who need or prefer voice input
3. **Power users** who want to reduce typing strain
4. **Developers** who want to customize their speech-to-text workflow

## Key Features

### Phase 1 (MVP)
- Push-to-talk dictation with Alt+Space hotkey
- Vosk backend (offline, lightweight)
- Whisper.cpp backend (offline, higher quality)
- Privacy: Disabled in password/PIN fields
- GNOME/IBus integration

### Phase 2
- Parakeet ONNX backend (local, high performance)
- HTTP backend (generic + OpenAI-compatible)
- Backend switching via settings UI
- Model download and management

### Phase 3 (Future)
- Always-on mode with VAD
- Global hotkey via GNOME Shell extension
- Custom voice commands

## Success Metrics

1. **Latency**: < 2 seconds from release of hotkey to text appearing
2. **Accuracy**: Comparable to Whisper "base" model quality
3. **Reliability**: No crashes or hangs during normal use
4. **Privacy**: Zero audio leakage in sensitive contexts
5. **Adoption**: Packagable for Fedora/Ubuntu repositories
