"""Analyze orientation usage by symbol base-name in GT ASC files."""
from __future__ import annotations
import re
from collections import defaultdict
from pathlib import Path

GT_DIR = Path("valid_convert/asc")
_SYMBOL_RE = re.compile(r"^SYMBOL\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\S+)\s*$")
_INSTNAME_RE = re.compile(r"^SYMATTR\s+InstName\s+(\S+)\s*$")


def parse_symbols(asc_path: Path):
    symbols = []
    current = None
    for line in asc_path.read_text(encoding="latin-1").splitlines():
        m = _SYMBOL_RE.match(line.strip())
        if m:
            current = {"name": m.group(1).replace("\\\\", "\\").split("\\")[-1].lower(), "orient": m.group(4)}
            continue
        mi = _INSTNAME_RE.match(line.strip())
        if mi and current is not None:
            current["inst"] = mi.group(1)
            symbols.append(current)
            current = None
    return symbols


def main():
    orient_by_name = defaultdict(lambda: defaultdict(int))
    for asc_path in sorted(GT_DIR.glob("*.asc")):
        for sym in parse_symbols(asc_path):
            orient_by_name[sym["name"]][sym["orient"]] += 1
    print(f"{'symbol':20s} {'orientations (count)'}")
    print("-" * 60)
    for name in sorted(orient_by_name):
        counts = orient_by_name[name]
        total = sum(counts.values())
        parts = [f"{o}:{c}" for o, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
        print(f"{name:20s} total={total:4d}  {', '.join(parts)}")


if __name__ == "__main__":
    main()
