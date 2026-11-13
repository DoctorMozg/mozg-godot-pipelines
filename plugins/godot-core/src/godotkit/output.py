"""What every command shares: exit codes and the one JSON line it prints."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping

EXIT_OK, EXIT_FAILED, EXIT_SETUP, EXIT_REFUSED = 0, 1, 2, 3
MAX_ISSUES_SHOWN = 20


def emit(payload: Mapping[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
