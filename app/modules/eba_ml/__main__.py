"""CLI entry point: python -m app.modules.eba_ml [train|hypotheses] ...

ml train  — run hyperparameter search, OOF refitting, and save results JSON.
           Requires a label array (y); T-2 adds E2/E3 label functions.
ml hypotheses — evaluate H1a, H3, H5 on a completed training run.
               H1b and H2 are pending T-2.
"""
from __future__ import annotations

import argparse
import sys


def cmd_train(args: argparse.Namespace) -> None:
    """Run ml train — requires E2/E3 labels (available in T-2)."""
    raise NotImplementedError(
        "ml train requires a label array (y). "
        "T-2 will add E2/E3 label functions. "
        "Pass --help for available options once T-2 is complete."
    )


def cmd_hypotheses(args: argparse.Namespace) -> None:
    """Run ml hypotheses."""
    from app.modules.eba_ml.application.evaluation.hypotheses import hypotheses

    hypotheses(args.run_dir, quick=args.quick)


def main() -> None:
    parser = argparse.ArgumentParser(prog="ml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_train = sub.add_parser("train", help="Run ML training pipeline (requires T-2 labels)")
    p_train.add_argument("--grid", default="semiannual")
    p_train.add_argument("--out-dir", dest="out_dir", default="data/ml")
    p_train.add_argument("--robustness", action="store_true")
    p_train.add_argument("--models", nargs="*")
    p_train.add_argument("--wall-clock-hours", dest="wall_clock_hours",
                         type=float, default=2.0)
    p_train.add_argument("--space", default="table35",
                         choices=["table35", "extended"])
    p_train.set_defaults(func=cmd_train)

    p_hyp = sub.add_parser("hypotheses", help="Evaluate H1a/H3/H5 on a training run")
    p_hyp.add_argument("run_dir", help="Directory containing results_*.json")
    p_hyp.add_argument("--quick", action="store_true",
                       help="Use reduced replicates and budget (for testing)")
    p_hyp.set_defaults(func=cmd_hypotheses)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
