"""Starts designkit from the plugin's own files.

`python3 -I` keeps PYTHONPATH and the user site off the path, so a stray json.py there cannot
replace a stdlib module.
"""

from __future__ import annotations

import sys
from pathlib import Path

MINIMUM_PYTHON = (3, 11)
SRC = Path(__file__).resolve().parents[1] / "src"


def run(argv: list[str]) -> int:
    if sys.version_info < MINIMUM_PYTHON:
        found = ".".join(str(part) for part in sys.version_info[:3])
        sys.stderr.write(f"designkit: needs Python 3.11 or newer, found {found}\n")
        return 2
    sys.path.insert(0, str(SRC))
    try:
        from designkit.cli import main
    except ImportError as error:
        sys.stderr.write(f"designkit: cannot load the package from {SRC}: {error}\n")
        return 2
    return int(main(argv))


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
