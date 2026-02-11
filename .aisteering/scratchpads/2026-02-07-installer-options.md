# Scratchpad: 2026-02-07 Installer Options

## Session Notes

- User asked for installer options so end users do not need terminal commands.
- Reviewed repo context:
  - Python/IBus/GNOME app with system dependencies (`README.md`, `pyproject.toml`).
  - Existing installation path is terminal-driven (`scripts/dev-install.sh`).
  - Existing project goal includes Fedora/Ubuntu packaging.
- Key technical constraint:
  - This is an IBus engine with host-level integration, so sandboxed formats (Flatpak/Snap) are high risk for first-class install UX.
- Recommendation direction:
  - Prefer native distro packages (`.deb`/`.rpm`) surfaced through GUI software centers.
  - Keep a GUI bootstrap installer only as a short-term bridge.

## Open Questions

1. Which distro should be first-class for UX (`Ubuntu` vs `Fedora`)?
2. Should we accept a browser download + double-click package flow for v1, or require store/repo install?
