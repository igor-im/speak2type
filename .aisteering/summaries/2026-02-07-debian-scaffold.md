# Debian Packaging Scaffold Summary

**Date**: 2026-02-07  
**Scope**: Add initial Debian packaging for `speak2type`

## What changed
- Added Debian packaging scaffold in `debian/`:
  - `debian/control`
  - `debian/rules`
  - `debian/changelog`
  - `debian/source/format`
  - `debian/copyright`
  - `debian/ibus-engine-speak2type`
  - `debian/speak2type.xml`
  - `debian/README.build.md`
- `debian/rules` installs:
  - Python package via `pybuild`
  - IBus launcher/component files
  - GSettings schema
  - formatting/numbers data files
- Follow-up fixes after package build failure:
  - `src/speak2type/model_managers/parakeet.py`: replaced invalid `callable | None` annotation with `Callable[[int, int], None] | None` (Python 3.13-safe).
  - `debian/rules`: run tests with `pytest` (`override_dh_auto_test` + `--test-pytest`).
  - `debian/control`: added `python3-pytest` in `Build-Depends`.
  - Added regression tests in `tests/test_model_managers.py`.

## Why
- User requested a no-terminal installation path; Debian packaging is the first lane for GUI-installable `.deb` builds.

## How to validate
- Parse changelog:
  - `dpkg-parsechangelog -ldebian/changelog`
- Run Python regression tests:
  - `.venv/bin/pytest -q tests/test_model_managers.py tests/test_types.py tests/test_backends.py`
- Build package:
  - `dpkg-buildpackage -us -uc -b`

## Notes / risks
- Final package build was completed by the user after dependency installation, producing `../speak2type_0.1.0-1_all.deb`.
- Full package build was not reproducible inside this agent session due system package install permission limits.
- Package currently ships as a single binary package (`speak2type`) for simplicity.

## Next steps
1. Test install/remove lifecycle and IBus registration on Ubuntu target.
2. Add CI packaging job to build `.deb` artifacts on tags/releases.
