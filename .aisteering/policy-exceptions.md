# Policy Exceptions

## Exception1: ENGINE_NO_BACKEND

**Date**: 2026-02-08
**Scope**: `src/speak2type/engine.py` — `_setup_backend()`

**Exception**: The IBus engine starts without a backend when no speech
recognition backend is installed (e.g. fresh install via apt).

**Rationale**: IBus requires the engine process to be running for the input
method to appear in GNOME Settings. If the engine crashes on startup because
no backend is installed, the user cannot even see or select speak2type, making
it impossible to reach the preferences UI to install a backend.

**Behavior**:
- Engine starts normally, PTT hotkey is active.
- If the user triggers dictation with no backend: a preedit message
  "No backend — open speak2type settings" is shown for 3 seconds, then
  cleared. No placeholder transcription is produced.
- The engine log clearly states: "No speech recognition backend installed.
  Open speak2type settings to install one."

**Not a silent fallback**: No audio is transcribed. No fake results are
produced. The user is explicitly told to configure a backend. This is a
deliberate first-run state, not a degradation.

## Exception 2: Model Download Defaults

**Date**: 2026-01-26

**Scope**: Model manager components (`src/model_managers/`)

**Exception**: The model download system may use sensible defaults for:

1. **Default model selection**: When no model is configured, automatically select the smallest/fastest model for the active backend.
2. **Download location**: Use XDG-compliant directories without explicit user configuration:
   - Models: `$XDG_DATA_HOME/speak2type/models/` (default: `~/.local/share/speak2type/models/`)
   - Cache: `$XDG_CACHE_HOME/speak2type/` (default: `~/.cache/speak2type/`)
3. **Model revision pinning**: Use pinned revisions from `models.json` when user doesn't specify a version.

**Rationale**:
- Users expect speech-to-text to "just work" after installation without manual model configuration.
- Following XDG Base Directory Specification is the standard Linux convention.
- Pinned model versions ensure reproducibility and security.

**Explicit behaviors**:
- Model downloads show progress and require user consent on first download.
- All model metadata (id, revision, sha256) is logged and verifiable.
- Users can override all defaults via settings UI or configuration files.

**Tests required**:
- Test default model selection for each backend
- Test XDG directory resolution with and without environment variables set

## Exception 3: GLOBAL_HOTKEY_GRACEFUL_DEGRADATION

**Date**: 2026-02-10
**Scope**: `src/speak2type/engine.py` — `do_enable()`, `src/speak2type/global_hotkey.py`

**Exception**: When the XDG Desktop Portal GlobalShortcuts interface is
unavailable (e.g. GNOME < 48, non-GNOME desktops without the portal), the
engine falls back to IBus-only key handling without the global hotkey.

**Rationale**: The global hotkey requires the GlobalShortcuts portal (GNOME
48+, KDE Plasma 6.1+). Older desktops don't have this portal. The engine
must still function for IBus-aware applications on these systems.

**Behavior**:
- `GlobalHotkeyListener.setup()` returns `False` if the portal is
  unreachable (D-Bus name not found, CreateSession fails, etc.).
- Engine logs: "Global hotkey not available (portal missing?)" at WARNING
  level.
- IBus key handling continues to work normally for IBus-aware apps.
- No crash, no error dialog, no placeholder behavior.

**Not a silent fallback**: The degradation is logged at WARNING level. The
feature is additive — IBus-aware apps never depended on the portal path.

**Tests required**:
- `test_no_session_bus`: setup() returns False when D-Bus is unavailable
- `test_create_session_dbus_error`: setup() returns False when portal is missing