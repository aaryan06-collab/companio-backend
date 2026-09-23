"""Trains and deploys the adaptive-difficulty model.

Always fits on ``TRAIN_DB ∪ LIVE_DB`` (demo baseline + real-time usage). If
the training gates are not met the previous model stays deployed and this
script explains why.

Usage (from ``server/``):
    python scripts/train_model.py
    python scripts/train_model.py --no-demo            # real-only training
    python scripts/train_model.py --live-db sqlite:///other.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.database import make_session  # noqa: E402
from app.ml import train as ml_train  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Train + deploy the adaptive difficulty model")
    parser.add_argument("--train-db", default=config.TRAIN_DATABASE_URL)
    parser.add_argument("--live-db", default=config.DATABASE_URL)
    parser.add_argument("--model-path", default=str(config.MODEL_PATH))
    parser.add_argument("--no-demo", action="store_true", help="Train on live data only")
    args = parser.parse_args()

    summary = ml_train.fit(
        train_session=make_session(args.train_db),
        live_session=make_session(args.live_db),
        model_path=Path(args.model_path),
        include_demo=not args.no_demo,
    )

    print(f"deployed={summary.deployed}")
    print(f"demo_samples={summary.demoSamples}")
    print(f"real_samples={summary.realSamples}")
    print(f"holdout_accuracy={summary.holdoutAccuracy}")
    print(f"baseline_accuracy={summary.baselineAccuracy}")
    print(f"trained_at={summary.trainedAt}")
    print(f"message={summary.message}")

    return 0 if summary.deployed else 2


if __name__ == "__main__":
    raise SystemExit(main())