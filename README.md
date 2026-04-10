# pylynxley

![Python](https://img.shields.io/badge/python-3.14%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-informational)
![License](https://img.shields.io/badge/license-LGPLv3-blue)
![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)

Tooling:
[![Ruff](https://img.shields.io/badge/ruff-enabled-46a758)](.pre-commit-config.yaml)
[![Basedpyright](https://img.shields.io/badge/basedpyright-enabled-2f6feb)](.pre-commit-config.yaml)
[![Ty](https://img.shields.io/badge/ty%20check-enabled-7a52cc)](.pre-commit-config.yaml)
[![Pytest Coverage](https://img.shields.io/badge/pytest-100%25%20coverage-brightgreen)](.pre-commit-config.yaml)

Quality and Security:
[![Vulture](https://img.shields.io/badge/vulture-enabled-5f6368)](.pre-commit-config.yaml)
[![Deptry](https://img.shields.io/badge/deptry-enabled-5f6368)](.pre-commit-config.yaml)
[![Detect Secrets](https://img.shields.io/badge/detect--secrets-enabled-5f6368)](.pre-commit-config.yaml)

Content and Config:
[![Yamllint](https://img.shields.io/badge/yamllint-enabled-5f6368)](.pre-commit-config.yaml)
[![Yamlfmt](https://img.shields.io/badge/yamlfmt-enabled-5f6368)](.pre-commit-config.yaml)
[![Markdownlint](https://img.shields.io/badge/markdownlint-enabled-5f6368)](.pre-commit-config.yaml)
[![mdformat](https://img.shields.io/badge/mdformat-enabled-5f6368)](.pre-commit-config.yaml)
[![Taplo](https://img.shields.io/badge/taplo-enabled-5f6368)](.pre-commit-config.yaml)

Python library for reading and writing Windows shortcut files (.lnk).

This project modernizes the pylnk3 approach for current Python and expanded
shortcut coverage. It parses .lnk files into a typed `Lnk` object, supports
edits and round-trip saving, and provides convenience constructors for creating
new links.

## Highlights

- Parse, inspect, and rewrite existing .lnk files.
- Create local, UNC, and UWP shortcuts with a unified API.
- Resolve target paths from LinkInfo, IDList, and ExtraData consistently.
- Test-backed behavior with local/network/UWP fixture coverage.

Supported scenarios:

- Local file/folder shortcuts.
- Remote UNC shortcuts.
- UWP application shortcuts.
- Mixed link data where LinkInfo, IDList, and ExtraData are reconciled.

## Requirements

- Python 3.14+

## Install

From this repository:

```sh
pip install -e .
```

For development:

```sh
pip install -e .[dev]
```

## Quick Start

```python
from pathlib import Path

from pylynxley.lnk import Lnk

lnk = Lnk.from_file(Path("example.lnk"))
print(lnk.path)

created = Lnk.create_local(target=r"C:\\Windows\\explorer.exe", description="Explorer")
created.save(Path("explorer.lnk"))
```

## CLI

The CLI supports parse and create flows for local, remote, and UWP links.

Run it as a module:

```sh
python -m pylynxley.lnk --help
```

### Parse existing .lnk file

```sh
python -m pylynxley.lnk parse LINK_FILE
```

Prints core fields (flags, show mode, resolved path, working directory,
arguments) and diagnostics for LinkInfo, IDList, and ExtraData.

### Create local .lnk file

```sh
python -m pylynxley.lnk create-local TARGET OUT_FILE \
  [--desc TEXT] [--args TEXT] [--icon ICON_PATH] [--workdir DIR] \
  [--window {normal,max,min}]
```

### Create remote (UNC) .lnk file

```sh
python -m pylynxley.lnk create-remote UNC_PATH OUT_FILE [--desc TEXT]
```

### Create UWP .lnk file

```sh
python -m pylynxley.lnk create-uwp PACKAGE_FAMILY TARGET OUT_FILE \
  [--location PATH] [--logo44 PATH] [--desc TEXT]
```

### CLI examples

```sh
python -m pylynxley.lnk parse src/pylynxley/tests/examples/local_file.lnk
python -m pylynxley.lnk create-local C:\Windows\explorer.exe \
  explorer.lnk --window max
python -m pylynxley.lnk create-remote \
  \\192.168.1.1\share\file.doc share-doc.lnk
python -m pylynxley.lnk create-uwp \
  Microsoft.WindowsCalculator_8wekyb3d8bbwe \
  Microsoft.WindowsCalculator_8wekyb3d8bbwe!App calc.lnk
```

## Python API

```python
from pathlib import Path

from pylynxley.lnk import Lnk

# Read and inspect an existing shortcut
lnk = Lnk.from_file(Path("example.lnk"))
print(lnk.path)

# Create and save a local shortcut
new_lnk = Lnk.create_local(
    target=r"C:\Windows\explorer.exe",
    description="Explorer",
)
new_lnk.save(Path("explorer.lnk"))
```

## Limitations

- Windows-focused behavior.
- This project targets shell link formats covered by the test fixtures, not
  every shortcut variant in the Windows ecosystem.

## Tests

```sh
uv run pytest --doctest-modules
uv run pytest --doctest-modules --cov=src/pylynxley --cov-report=term-missing
```

## Notes

- Behavior is validated against local, network, and UWP fixture shortcuts in
  `src/pylynxley/tests/examples`.
- CLI entrypoint behavior is covered by dedicated tests.
