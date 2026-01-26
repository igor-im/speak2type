# Architecture

## Overview

speak2type is an IBus input method engine that captures audio, transcribes it using pluggable backends, and commits the resulting text to the focused application. The architecture separates concerns into distinct layers: input handling, audio capture, speech recognition, and text processing.

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Application                          │
│                    (any IBus-aware app)                         │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ commit_text()
                              │
┌─────────────────────────────────────────────────────────────────┐
│                         IBus Daemon                              │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      speak2type Engine                           │
│  ┌──────────────┐  ┌────────────────┐  ┌──────────────────────┐ │
│  │ State Machine│  │ Audio Capture  │  │ Text Processing      │ │
│  │              │  │                │  │ (formatting, commands)│ │
│  │ IDLE         │  │ pipewiresrc    │  └──────────────────────┘ │
│  │ RECORDING    │  │ or pulsesrc    │                           │
│  │ TRANSCRIBING │  │                │  ┌──────────────────────┐ │
│  │ COMMITTING   │  │ GStreamer      │  │ Backend Registry     │ │
│  └──────────────┘  │ pipeline       │  │                      │ │
│                    └────────────────┘  │ Vosk │ Whisper │ ... │ │
│                                        └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Engine (`src/engine.py`)

The IBus engine handles:
- Key events (press/release for push-to-talk)
- State machine transitions
- Property updates (status, modes)
- Privacy checks (password field detection)
- Text commit to focused application

**State Machine:**
```
IDLE ──[Alt+Space press]──► RECORDING
  ▲                              │
  │                    [Alt+Space release]
  │                              ▼
  └───[commit_text()]──── TRANSCRIBING
```

### 2. Audio Capture (`src/audio_capture.py`)

GStreamer pipeline for microphone capture:
```
pipewiresrc/pulsesrc ! audioconvert ! audioresample !
audio/x-raw,format=S16LE,channels=1,rate=16000 ! appsink
```

Responsibilities:
- Runtime detection of pipewiresrc vs pulsesrc
- Buffer audio during RECORDING state
- Output PCM 16kHz mono S16LE

### 3. Backend Interface (`src/backends/`)

Pluggable speech recognition backends:

```python
class Backend(Protocol):
    id: str
    name: str

    def transcribe(self, segment: AudioSegment, locale_hint: str,
                   options: dict) -> TranscriptResult: ...
```

**Implementations:**
- `VoskBackendAdapter`: Wraps upstream sttgstvosk.py
- `WhisperBackendAdapter`: Wraps upstream sttgstwhisper.py
- `ParakeetBackend`: ONNX-based via onnx-asr
- `HttpBackend`: Generic + OpenAI-compatible

### 4. Worker Thread (`src/worker.py`)

Transcription runs in a separate thread to avoid blocking IBus:

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│ GStreamer   │────►│ Worker Thread    │────►│ Main Loop   │
│ callbacks   │     │ (transcription)  │     │ idle_add()  │
│ (recording) │     │                  │     │ commit_text │
└─────────────┘     └──────────────────┘     └─────────────┘
```

### 5. Text Processing (`src/upstream/sttsegmentprocess.py`)

From upstream - handles:
- Formatting rules (capitalization, punctuation)
- Voice commands (cancel, delete, etc.)
- Digit conversion

### 6. Model Management (`src/model_managers/`)

XDG-compliant model storage:
```
$XDG_DATA_HOME/speak2type/models/
├── vosk/
├── whisper/
└── parakeet/
```

Pinned model downloads with sha256 verification.

## Data Flow

### Push-to-Talk Flow

1. **User presses Alt+Space**
   - `do_process_key_event()` detects press
   - State → RECORDING
   - Audio pipeline starts

2. **User speaks**
   - GStreamer buffers audio frames
   - appsink accumulates PCM data

3. **User releases Alt+Space**
   - `do_process_key_event()` detects release (RELEASE_MASK)
   - State → TRANSCRIBING
   - Audio buffer sent to worker thread

4. **Worker transcribes**
   - Backend.transcribe() called
   - Result queued for main loop

5. **Main loop commits text**
   - `GLib.idle_add()` schedules commit
   - `commit_text()` sends to IBus
   - State → IDLE

## Key Decisions

### 1. Adapter Pattern for Backends

**Decision**: Wrap upstream sttgst* files rather than rewrite them.

**Rationale**:
- Preserves upstream compatibility
- Easier to port future improvements from Fedora
- Backend interface is for new backends

### 2. pipewiresrc Preferred

**Decision**: Try pipewiresrc first, fallback to pulsesrc.

**Rationale**:
- pipewiresrc is native PipeWire
- pulsesrc works via pipewire-pulse but adds latency
- Runtime detection for compatibility

### 3. Transcription in Worker Thread

**Decision**: Never block IBus main loop with inference.

**Rationale**:
- IBus engines must respond to key events quickly
- Heavy models (Whisper, Parakeet) can take seconds
- Worker thread isolates latency

### 4. Privacy by Default

**Decision**: Disable recording in PASSWORD/PIN fields unconditionally.

**Rationale**:
- Privacy is non-negotiable
- Users can't accidentally dictate passwords
- Implemented via `do_set_content_type()`

### 5. XDG Directories for Models

**Decision**: Use standard XDG paths, not custom locations.

**Rationale**:
- Follows Linux conventions
- Works with containerization
- Users can relocate data easily
