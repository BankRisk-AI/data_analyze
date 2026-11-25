"""CLI entry point: python -m app.modules.eba_ml [train|hypotheses] ...

ml train  — run hyperparameter search, OOF refitting, and save results JSON.
ml hypotheses — evaluate H1a–H3, H5 on a completed training run.
"""
from __future__ import annotations

import argparse
import sys


def cmd_train(args: argparse.Namespace) -> None:
    """Run ml train with E2/E3 labels (§3.5)."""
    from app.core.config import get_schema
    from app.core.database import connect
    from app.modules.eba_ml.application.training.train import train

    conn = connect(get_schema())
    try:
        train(
            conn,
            label=args.label,
            grid=args.grid,
            out_dir=args.out_dir,
            robustness=args.robustness,
            models=args.models,
            wall_clock_hours=args.wall_clock_hours,
            space=args.space,
            reuse_search=args.reuse_search,
            tail_quantile=args.tail_quantile,
            sensitivity=args.sensitivity,
        )
    finally:
        conn.close()


def cmd_hypotheses(args: argparse.Namespace) -> None:
    """Run ml hypotheses."""
    from app.modules.eba_ml.application.evaluation.hypotheses import hypotheses

    hypotheses(args.run_dir, quick=args.quick)


def main() -> None:
    parser = argparse.ArgumentParser(prog="ml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_train = sub.add_parser("train", help="Run ML training pipeline (§3.5)")
    p_train.add_argument("--label", default=None,
                         help="Target label (E1, E2, E3, E2_or_E3); default from config/ml.yaml")
    p_train.add_argument("--grid", default="semiannual")
    p_train.add_argument("--out-dir", dest="out_dir", default="data/ml")
    p_train.add_argument("--robustness", action="store_true")
    p_train.add_argument("--models", nargs="*")
    p_train.add_argument("--wall-clock-hours", dest="wall_clock_hours",
                         type=float, default=2.0)
    p_train.add_argument("--space", default="table35",
                         choices=["table35", "extended"])
    p_train.add_argument("--reuse-search", dest="reuse_search", action="store_true",
                         help="Skip search if <out-dir>/search.json exists and hash matches")
    p_train.add_argument("--tail-quantile", dest="tail_quantile", type=float, default=None,
                         help="Tail quantile for E2/E3 threshold (overrides config/ml.yaml)")
    p_train.add_argument("--sensitivity", default=None,
                         help="Sensitivity label stored in result JSON (e.g. 'q975', 'E3')")
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
