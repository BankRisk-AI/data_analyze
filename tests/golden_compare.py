"""Golden comparison: verify new training/hypotheses results are bit-identical to 5bR runs.

Usage:
  python tests/golden_compare.py

Compares:
  data/ml/golden_t35/   vs  data/ml/5bR_t35/
  data/ml/golden_ext/   vs  data/ml/5bR/

Prints "PASS" or the first differing key per file pair.
Ignores: timestamp, paths (run, run_dir keys).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

IGNORE_KEYS = {"run", "run_dir", "timestamp"}

COMPARISONS = [
    ("data/ml/golden_t35", "data/ml/5bR_t35"),
    ("data/ml/golden_ext", "data/ml/5bR"),
]


def _flatten(obj, prefix=""):
    """Flatten nested dict/list into {dotted.path: value}."""
    items = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in IGNORE_KEYS:
                continue
            items.update(_flatten(v, f"{prefix}.{k}" if prefix else k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            items.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        items[prefix] = obj
    return items


def compare_json(path_a: Path, path_b: Path) -> str | None:
    """Return first differing key, or None if identical (ignoring IGNORE_KEYS)."""
    a = _flatten(json.loads(path_a.read_text()))
    b = _flatten(json.loads(path_b.read_text()))
    all_keys = sorted(set(a) | set(b))
    for key in all_keys:
        if key not in a:
            return f"MISSING in new: {key}"
        if key not in b:
            return f"MISSING in golden: {key}"
        va, vb = a[key], b[key]
        if isinstance(va, float) and isinstance(vb, float):
            if va != vb:
                return f"{key}: {va} != {vb}"
        elif va != vb:
            return f"{key}: {va!r} != {vb!r}"
    return None


def main():
    all_pass = True
    for new_dir, golden_dir in COMPARISONS:
        new_path = Path(new_dir)
        golden_path = Path(golden_dir)
        if not new_path.exists():
            print(f"SKIP  {new_dir} — not yet generated (run ml train first)")
            continue
        if not golden_path.exists():
            print(f"SKIP  {golden_dir} — golden directory not found")
            continue
        for suffix in ("results_*.json", "hypotheses.json"):
            for golden_file in golden_path.glob(suffix):
                new_file = new_path / golden_file.name
                if not new_file.exists():
                    print(f"MISSING  {new_file}")
                    all_pass = False
                    continue
                diff = compare_json(new_file, golden_file)
                if diff is None:
                    print(f"PASS  {new_file.name}  ({new_dir} vs {golden_dir})")
                else:
                    print(f"DIFF  {new_file.name}  first difference: {diff}")
                    all_pass = False
    if all_pass:
        print("\nAll comparisons passed.")
    else:
        print("\nSome comparisons failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
