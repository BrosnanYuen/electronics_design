"""Score generated ASC against ground-truth ASC by symbol orientation, position, and set fidelity."""
from __future__ import annotations
import math
import re
import sys
from pathlib import Path

GT_DIR = Path("valid_convert/asc")
GEN_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/test")

_SYMBOL_RE = re.compile(r"^SYMBOL\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\S+)\s*$")
_INSTNAME_RE = re.compile(r"^SYMATTR\s+InstName\s+(\S+)\s*$")


def parse_symbols(asc_path: Path):
    symbols = {}
    current_symbol = None
    try:
        lines = asc_path.read_text(encoding="latin-1").splitlines()
    except OSError:
        return symbols
    for line in lines:
        m = _SYMBOL_RE.match(line.strip())
        if m:
            current_symbol = {
                "name": m.group(1),
                "x": int(m.group(2)),
                "y": int(m.group(3)),
                "orient": m.group(4),
            }
            continue
        mi = _INSTNAME_RE.match(line.strip())
        if mi and current_symbol is not None:
            inst = mi.group(1)
            symbols[inst] = current_symbol
            current_symbol = None
    return symbols


def score_file(gt_path: Path, gen_path: Path):
    gt = parse_symbols(gt_path)
    gen = parse_symbols(gen_path) if gen_path.exists() else {}
    gt_keys = set(gt.keys())
    gen_keys = set(gen.keys())
    set_fidelity = 1.0 if gt_keys == gen_keys else len(gt_keys & gen_keys) / max(len(gt_keys), 1)
    matched = sorted(gt_keys & gen_keys)
    orient_correct = sum(1 for k in matched if gt[k]["orient"] == gen[k]["orient"])
    orient_acc = orient_correct / len(matched) if matched else 0.0
    if len(matched) >= 2:
        nn_correct = 0
        dist_correct = 0
        for k in matched:
            others_gt = [(o, abs(gt[k]["x"] - gt[o]["x"]) + abs(gt[k]["y"] - gt[o]["y"])) for o in matched if o != k]
            others_gen = [(o, abs(gen[k]["x"] - gen[o]["x"]) + abs(gen[k]["y"] - gen[o]["y"])) for o in matched if o != k]
            nn_gt = min(others_gt, key=lambda t: t[1])[0] if others_gt else None
            nn_gen = min(others_gen, key=lambda t: t[1])[0] if others_gen else None
            if nn_gt == nn_gen:
                nn_correct += 1
        for i, k in enumerate(matched):
            for o in matched[i+1:]:
                d_gt = abs(gt[k]["x"] - gt[o]["x"]) + abs(gt[k]["y"] - gt[o]["y"])
                d_gen = abs(gen[k]["x"] - gen[o]["x"]) + abs(gen[k]["y"] - gen[o]["y"])
                if d_gt > 0:
                    ratio = d_gen / d_gt
                    if 0.5 <= ratio <= 2.0:
                        dist_correct += 1
        total_pairs = len(matched) * (len(matched) - 1) // 2
        nn_acc = nn_correct / len(matched) if matched else 0.0
        dist_acc = dist_correct / total_pairs if total_pairs > 0 else 0.0
    else:
        nn_acc = 1.0
        dist_acc = 1.0
    pair_quality = (nn_acc + dist_acc) / 2
    geo_mean = math.sqrt(orient_acc * pair_quality) if (orient_acc > 0 and pair_quality > 0) else 0.0
    score = geo_mean * 0.95 + set_fidelity * 0.05
    return {
        "gt": len(gt_keys), "gen": len(gen_keys),
        "orient": f"{orient_correct}/{len(matched)} ({orient_acc*100:.0f}%)",
        "nn": f"{nn_acc*100:.0f}%", "dist": f"{dist_acc*100:.0f}%",
        "set": f"{set_fidelity*100:.0f}%", "score": f"{score*100:.1f}%",
    }


def main():
    total_score = 0.0
    count = 0
    generated_paths = sorted(GEN_DIR.glob("*.asc"), key=lambda path: path.name.casefold())
    if not generated_paths:
        print(f"No generated .asc files found in {GEN_DIR}.")
        return
    for gen_path in generated_paths:
        stem = gen_path.stem
        gt_path = GT_DIR / gen_path.name
        if not gt_path.exists():
            print(f"{stem:55s} [GROUND TRUTH MISSING]")
            continue
        r = score_file(gt_path, gen_path)
        print(f"{stem:55s} GT={r['gt']:2d} GEN={r['gen']:2d} O={r['orient']:18s} NN={r['nn']:5s} D={r['dist']:5s} S={r['set']:5s} => {r['score']:6s} [OK]")
        total_score += float(r["score"].rstrip("%"))
        count += 1
    if count:
        print(f"\nAverage score across {count} files: {total_score/count:.1f}%")
    else:
        print("No generated files with matching ground truth found.")


if __name__ == "__main__":
    main()
