#!/usr/bin/env python3
import json
import os
import sys

if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} <directory>")
    sys.exit(1)

DIR = sys.argv[1]

if not os.path.isdir(DIR):
    print(f"Error: '{DIR}' is not a directory")
    sys.exit(1)

ZERO_KEYS = {"X", "Y", "ROTATION"}
CLEAR_KEYS = {"RECTANGLE", "PINS"}

count = 0
for fname in os.listdir(DIR):
    if not fname.endswith(".json"):
        continue
    fpath = os.path.join(DIR, fname)
    with open(fpath, "r") as f:
        data = json.load(f)

    for comp_name, comp in data.items():
        for key in list(comp.keys()):
            if key in ZERO_KEYS:
                comp[key] = 0
            elif key in CLEAR_KEYS:
                comp[key] = []

    with open(fpath, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    count += 1

print(f"Done. Processed {count} files in {DIR}")
