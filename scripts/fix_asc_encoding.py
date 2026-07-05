#!/usr/bin/env python3
"""
Recursively find .asc (LTspice schematic) files and fix UTF-8 encoded
micro sign (0xC2 0xB5 -> 0xB5) to single-byte Latin-1 that LTspice expects.
"""

import os
import sys


def fix_asc_file(filepath, dry_run=False):
    with open(filepath, "rb") as f:
        data = f.read()

    original = data
    data = data.replace(b"\xc2\xb5", b"\xb5")

    if data == original:
        return False

    if not dry_run:
        with open(filepath, "wb") as f:
            f.write(data)

    return True


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    dry_run = "--dry-run" in sys.argv

    fixed_count = 0
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            if fname.endswith(".asc"):
                fullpath = os.path.join(dirpath, fname)
                if fix_asc_file(fullpath, dry_run):
                    fixed_count += 1
                    print(f"{'[DRY RUN] ' if dry_run else ''}Fixed: {fullpath}")

    print(f"\nDone. {fixed_count} file(s) {'would be ' if dry_run else ''}fixed.")


if __name__ == "__main__":
    main()
