# Scratchpad: 2026-02-07 Debian Scaffold

## Session Notes

- User approved creating Debian packaging scaffold.
- Added `debian/` directory with:
  - `control`, `rules`, `changelog`, `copyright`, `source/format`
  - `ibus-engine-speak2type` launcher script
  - `speak2type.xml` IBus component definition
- Packaging approach:
  - Build Python package with `dh` + `pybuild` (PEP 517 plugin).
  - Install extra runtime assets in `override_dh_auto_install`:
    - IBus component XML
    - Engine launcher in `/usr/libexec`
    - GSettings schema
    - Formatting and numbers data files
- Added `debian/README.build.md` with dependency, build, install, and activation commands.
- Attempted to install build dependencies from this session:
  - `sudo apt-get ...` failed due sudo authentication.
  - `apt-get ...` (escalated) failed due `/var/lib/apt/lists/lock` permission denied.
- User provided new packaging failure output from `dh_auto_test`:
  - Python 3.13 import error in `model_managers/parakeet.py` due `callable | None` annotation.
  - Debian build test runner used `unittest discover` while test suite is pytest-based.
  - `pytest` missing in Debian build environment.
- Applied follow-up fixes:
  - `src/speak2type/model_managers/parakeet.py`: switched `progress_callback` annotation to `Callable[[int, int], None] | None`.
  - `debian/rules`: set pybuild tests to pytest via `override_dh_auto_test`.
  - `debian/control`: added `python3-pytest` to `Build-Depends`.
  - Added regression tests: `tests/test_model_managers.py`.
- User reran build after installing missing dependency and reported success:
  - `dpkg-buildpackage -us -uc -b` completed.
  - Artifact built: `../speak2type_0.1.0-1_all.deb`.

## Validation

- `dpkg-parsechangelog -ldebian/changelog` succeeded.
- `dpkg-buildpackage -us -uc -b` failed due missing build dependencies in current environment:
  - `debhelper-compat (= 13)`
  - `dh-sequence-python3`
  - `pybuild-plugin-pyproject`
  - `python3-all`
  - `python3-build`
- After Debian rules/control updates in this session:
  - `.venv/bin/pytest -q tests/test_model_managers.py tests/test_types.py tests/test_backends.py` -> `27 passed, 3 skipped`.
  - `PYTHONPATH=src python3.13 -c "from speak2type.model_managers import ParakeetModelManager"` -> success.
  - `dpkg-buildpackage -us -uc -b` (in this environment) now fails only on missing `python3-pytest`.
- User-provided packaging output (after dependency install) shows:
  - `24 passed, 6 skipped, 1 warning` during package test phase.
  - `dpkg-deb: building package 'speak2type' in '../speak2type_0.1.0-1_all.deb'.`

## Open Questions

1. Should package name stay `speak2type` or change to `ibus-speak2type` before publishing?
2. Should we split backend extras into subpackages later (for smaller base install)?
