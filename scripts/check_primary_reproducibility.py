"""Verify T3_primary and T3_primary_check produce identical OOF and final-test predictions."""
import json
import sys
from pathlib import Path


def load_preds(run_dir: str) -> tuple[dict, dict]:
    p = next(Path(run_dir).glob("results_*.json"))
    r = json.loads(p.read_text())
    return r.get("predictions", {}), r.get("test_predictions", {})


def compare(a: dict, b: dict, name: str) -> int:
    errors = 0
    all_keys = set(a) | set(b)
    for model in all_keys:
        preds_a = a.get(model, {})
        preds_b = b.get(model, {})
        if preds_a != preds_b:
            diff = {k: (preds_a.get(k), preds_b.get(k))
                    for k in set(preds_a) | set(preds_b)
                    if preds_a.get(k) != preds_b.get(k)}
            print(f"MISMATCH {name}/{model}: {len(diff)} differing keys", file=sys.stderr)
            errors += 1
        else:
            print(f"OK {name}/{model}: {len(preds_a)} predictions identical")
    return errors


if __name__ == "__main__":
    primary = sys.argv[1] if len(sys.argv) > 1 else "data/ml/T3_primary"
    check = sys.argv[2] if len(sys.argv) > 2 else "data/ml/T3_primary_check"

    oof_a, test_a = load_preds(primary)
    oof_b, test_b = load_preds(check)

    errs = compare(oof_a, oof_b, "OOF") + compare(test_a, test_b, "final_test")
    if errs:
        print(f"FAIL: {errs} mismatches", file=sys.stderr)
        sys.exit(1)
    else:
        print("PASS: T3_primary and T3_primary_check predictions are identical")
