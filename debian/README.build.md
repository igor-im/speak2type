# Building speak2type Debian Packages

This repository includes a Debian packaging scaffold under `debian/`.

## 1. Install build dependencies (Ubuntu/Debian)

```bash
sudo apt-get update
sudo apt-get install -y \
  debhelper \
  dh-python \
  pybuild-plugin-pyproject \
  python3-all \
  python3-build \
  python3-pytest \
  python3-setuptools \
  python3-wheel
```

## 2. Build the binary package

From the repository root:

```bash
dpkg-buildpackage -us -uc -b
```

Artifacts are written one directory above the repo (for example):

- `../speak2type_0.1.0-1_all.deb`
- `../speak2type_0.1.0-1_amd64.buildinfo`
- `../speak2type_0.1.0-1_amd64.changes`

## 3. Install the package

```bash
sudo apt-get install -y ../speak2type_0.1.0-1_all.deb
```

## 4. Post-install activation

```bash
ibus restart
```

Then add **Speech To Text** as an input source in GNOME Settings.
