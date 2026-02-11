# 2026-02-10: GlobalShortcuts Provider Shim Workaround

## What changed

### Problem
`BindShortcuts` returned response code=2 from the IBus engine (host process),
while identical calls from VSCode (snap) succeeded. Root cause: Ubuntu bug
[LP#2107533](https://bugs.launchpad.net/ubuntu/+source/gnome-control-center/+bug/2107533)
where `gnome-control-center-global-shortcuts-provider` crashes/returns
`UnknownMethod` for non-snap apps due to a null pointer in
`cc_global_shortcut_dialog_new`.

### Root cause chain
1. IBus engine is a host (non-snap) process → empty `app_id`
2. Portal backend calls system `GlobalShortcutsProvider` which fails for host apps
3. Portal returns code=2 (error) to the engine

### Fix: provider shim in `global_hotkey.py`
- **Host app registration**: call `org.freedesktop.host.portal.Registry.Register`
  with `ibus-setup-speak2type` app_id (matching existing .desktop file)
- **Provider shim**: claim `org.gnome.Settings.GlobalShortcutsProvider` bus name
  with a minimal implementation that auto-approves shortcuts. The shim intercepts
  the `BindShortcuts` call before it reaches the broken system provider.
- Both degrade gracefully if unavailable (logged, not fatal)

### Files modified
- `src/speak2type/global_hotkey.py` — added `_register_host_app()`,
  `_start_provider_shim()`, `_stop_provider_shim()`, `_on_provider_method_call()`
- `tests/test_global_hotkey.py` — added 7 tests for provider shim and host
  registration (21 total, up from 14)

## How to validate
```bash
PYTHONPATH=src python3 -m pytest tests/test_global_hotkey.py -q  # 21 passed
sudo dpkg -i ../speak2type_0.1.0-1_all.deb && ibus restart
# Focus VSCode → hold configured PTT hotkey → verify recording starts
# Check ~/.cache/speak2type/engine.log for "Global hotkey active" line
```

## Risks
- Provider shim claims a well-known D-Bus name — if a future Ubuntu fix ships a
  working `gnome-control-center-global-shortcuts-provider`, both will race for
  the name. The shim uses `Gio.BusNameOwnerFlags.NONE` (no REPLACE), so the
  system provider wins if it starts first. When the Ubuntu fix lands the shim
  becomes a no-op.
- The shim auto-approves all shortcuts without showing a confirmation dialog.
  This is acceptable because the user explicitly configures the hotkey in
  speak2type preferences.

## Next steps
- End-to-end verification after deb install + IBus restart
- Commit changes to `bux/engine` branch
