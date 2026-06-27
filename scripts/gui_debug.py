"""Launch the path tracing debug GUI through the public package API."""

from __future__ import annotations

from pathlib import Path
import sys

_ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
_SOURCE_DIRECTORY = _ROOT_DIRECTORY / "src"

if str(_SOURCE_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SOURCE_DIRECTORY))

from electronics_design import gui_debug


def main() -> int:
    gui_debug()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
