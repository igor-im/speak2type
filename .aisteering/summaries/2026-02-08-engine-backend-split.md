# Summary: Engine/Backend Architecture Split

**Date**: 2026-02-08
**Branch**: `bux/engine`

## What changed

Split the architecture so the deb package installs only the engine + IBus
wiring (system deps), while backends are managed at runtime by the app with a
GTK4/Adwaita preferences UI.

### New files
- `src/speak2type/backend_manager.py` — `BackendSpec` registry and
  `BackendManager` class for checking/installing/uninstalling pip deps and
  model managers per backend.
- `src/speak2type/preferences.py` — Adwaita PreferencesWindow with three
  pages: Backends (install/remove/select), Models (download/remove), General
  (record mode, audio source). Entry point: `python3 -m speak2type.preferences`.
- `debian/ibus-setup-speak2type` — Shell launcher for the preferences UI.
- `.aisteering/policy-exceptions.md` — Documents the ENGINE_NO_BACKEND
  exception (engine starts without backend on fresh install).
- `tests/test_backend_manager.py` — Tests for BackendSpec, install/uninstall,
  model manager integration.

### Modified files
- `src/speak2type/engine.py` — `_setup_backend()` no longer raises RuntimeError
  when no backend is installed. Instead the engine starts without a worker and
  shows a "No backend — open speak2type settings" preedit message when the user
  tries to dictate. Added `_clear_no_backend_message()` method.
- `debian/control` — Removed `python3-numpy`, `python3-onnxruntime`,
  `python3-huggingface-hub` from Depends. Added `python3-pip`.
- `debian/rules` — Added install line for `ibus-setup-speak2type`.
- `debian/speak2type.xml` — Added `<setup>` element pointing to the setup script.

### Deleted files
- `debian/speak2type.postinst` — Removed the broken pip-install-as-root hack.

## Why

The previous approach hardcoded backend Python dependencies in the deb package
and used a postinst `pip install` as root for onnx-asr (which has no apt
package). This broke on modern Ubuntu due to PEP 668 (externally managed
environment). The new architecture lets the deb be a thin system-integration
package while the app manages backends in userspace.

## How to validate

```bash
# Run tests
PYTHONPATH=src python3 -m pytest tests/ -q

# Build deb
dpkg-buildpackage -us -uc -b

# Install (note: no backend deps pulled in)
sudo apt install ../speak2type_0.1.0-1_all.deb

# Restart IBus
ibus restart

# Open preferences (IBus → speak2type → Preferences, or directly):
python3 -m speak2type.preferences
```

## Notes/risks

- `pip install --user` puts packages in `~/.local/lib/python3.x/`, which is
  on `sys.path` for the user but NOT for root. The engine runs as the user's
  session process so this is fine.
- The preferences window uses code-based Adwaita widgets (no .ui template).
  A future iteration could use GtkBuilder XML for better i18n support.
- Model download progress is not yet shown granularly — the UI shows a spinner
  but no percentage. The `ParakeetModelManager.download_model` supports a
  `progress_callback` parameter for future use.

## Next steps

- Install the deb and test the full flow: install backend, download model,
  restart engine, verify transcription works.
- Consider adding a first-run notification when the engine detects no backend.
- Pin model SHA256 hashes before production deployment.
