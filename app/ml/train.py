"""Training pipeline for the adaptive-difficulty model.

Runs as a script (``scripts/train_model.py``) or on demand via the admin
endpoint. It always fits on ``TRAIN_DB ∪ LIVE_DB``:

* ``TRAIN_DB`` (demo.db) - seeded demo sessions, frozen training baseline.
* ``LIVE_DB`` (companio.db) - real-time usage pushed by running devices.

Deployment gates (see config): minimum total samples, minimum domain count,
minimum patient coverage, and holdout accuracy must beat a majority-class
baseline by the configured margin. Unless all gates pass the previous model
stays deployed and the pipeline reports why it skipped.
"""

from __future__ import annotations

import datetime as dt
import tempfile
from dataclasses import dataclass
from pathlib import Path

import joblib
from sqlalchemy import select
from sqlalchemy.orm import Session
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .. import config, models
from . import features
from .service import ModelCard


@dataclass
class TrainSummary:
    deployed: bool
    trainedAt: str | None = None
    demoSamples: int = 0
    realSamples: int = 0
    holdoutAccuracy: float | None = None
    baselineAccuracy: float | None = None
    message: str = ""


def collect_all(session: Session) -> list[models.ActivityRecord]:
    return session.scalars(select(models.ActivityRecord)).all()


def build_frame(records: list[models.ActivityRecord]) -> tuple[list[dict], list[int]]:
    groups = features.group_history(records)
    first_dates = features.patient_first_dates(records)
    rows: list[dict] = []
    targets: list[int] = []
    for (patient, category), ordered in groups.items():
        for i, row in enumerate(ordered):
            rows.append(features.row_features(row, ordered[: i + 1], first_dates[patient]))
            targets.append(features.difficulty_index(row.difficulty))
    return rows, targets


def _X(rows: list[dict]):
    import numpy as np  # type: ignore

    if not rows:
        return np.empty((0, len(features.FEATURE_COLUMNS)), dtype=object)
    return np.array([[r[c] for c in features.FEATURE_COLUMNS] for r in rows], dtype=object)


def _model_pipeline() -> Pipeline:
    preprocess = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore"), [0]),
            ("num", StandardScaler(), [1, 2, 3, 4, 5, 6, 7]),
        ]
    )
    return Pipeline(
        steps=[
            ("pre", preprocess),
            (
                "clf",
                LogisticRegression(
                    solver="lbfgs",
                    max_iter=2000,
                    class_weight="balanced",
                    random_state=config.RANDOM_SEED,
                ),
            ),
        ]
    )


def fit(
    train_session: Session,
    live_session: Session,
    model_path: Path,
    include_demo: bool = True,
) -> TrainSummary:
    train_records = collect_all(train_session)
    live_records = collect_all(live_session)

    combined = train_records + live_records if include_demo else live_records

    demos = sum(1 for r in combined if r.source == "demo")
    reals = sum(1 for r in combined if r.source != "demo")

    def fail(message: str) -> TrainSummary:
        return TrainSummary(deployed=False, demoSamples=demos, realSamples=reals, message=message)

    if len(combined) < config.MIN_TRAINING_SAMPLES:
        return fail(f"training skipped: {len(combined)} samples < {config.MIN_TRAINING_SAMPLES}")

    domains = {r.category for r in combined}
    if len(domains) < config.MIN_TRAINING_DOMAINS:
        return fail(f"training skipped: {len(domains)} domain(s) < {config.MIN_TRAINING_DOMAINS}")

    patients = {r.patient_account_id for r in combined}
    if len(patients) < config.MIN_PATIENT_COVERAGE:
        return fail(f"training skipped: patient coverage < {config.MIN_PATIENT_COVERAGE}")

    rows, targets = build_frame(combined)
    X = _X(rows)

    import numpy as np  # type: ignore

    y = np.array(targets, dtype=np.int64)
    if len(np.unique(y)) < 2:
        return fail("training skipped: target difficulty has a single class")

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=config.HOLDOUT_FRACTION,
        stratify=y if len(np.unique(y)) >= 2 else None,
        random_state=config.RANDOM_SEED,
    )

    pipeline = _model_pipeline()
    pipeline.fit(X_train, y_train)
    preds = pipeline.predict(X_test)

    baseline = float(np.bincount(y_test).max() / len(y_test)) if len(y_test) else 0.0
    holdout = float(accuracy_score(y_test, preds)) if len(y_test) else 0.0

    if holdout < config.MIN_HOLDOUT_ACCURACY:
        return fail(
            f"training skipped: holdout accuracy {holdout:.3f} < {config.MIN_HOLDOUT_ACCURACY}"
        )
    if holdout - baseline < config.MIN_HOLDOUT_MARGIN:
        return fail(
            f"training skipped: model ({holdout:.3f}) does not beat majority baseline ({baseline:.3f}) by the required margin"
        )

    card = ModelCard(
        deployed=True,
        trainedAt=dt.datetime.now().isoformat(timespec="seconds"),
        demoSamples=demos,
        realSamples=reals,
        holdoutAccuracy=round(holdout, 4),
        baselineAccuracy=round(baseline, 4),
        domains=sorted(domains),
        message=f"holdout {holdout:.2%} vs baseline {baseline:.2%}",
    )

    bundle = {
        "transformer": pipeline.named_steps["pre"],
        "model": pipeline.named_steps["clf"],
        "card": card,
    }

    model_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=model_path.parent, prefix=".model-", delete=False) as tmp:
        joblib.dump(bundle, tmp)
        tmp_path = Path(tmp.name)
    tmp_path.replace(model_path)

    return TrainSummary(
        deployed=True,
        trainedAt=card.trainedAt,
        demoSamples=demos,
        realSamples=reals,
        holdoutAccuracy=holdout,
        baselineAccuracy=baseline,
        message=card.message,
    )