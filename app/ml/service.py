"""Rules fusion + model inference for adaptive difficulty.

The model is a small multiclass classifier trained on real+demo activity
records. A rules engine (mirroring the app's ``AdaptiveRules``) is kept as a
guaranteed fallback: when the model is missing, unconfident, or lacks domain
coverage, the endpoint returns ``source: rules`` so the behaviour can never
regress below the offline app experience.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import joblib

from .. import config, models
from . import features


@dataclass
class ModelCard:
    deployed: bool = False
    trainedAt: str | None = None
    demoSamples: int = 0
    realSamples: int = 0
    holdoutAccuracy: float | None = None
    baselineAccuracy: float | None = None
    domains: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class Prediction:
    difficulty: str
    confidence: float
    source: str  # 'ml' | 'rules'


class _Bundle:
    def __init__(self, payload: dict):
        self.transformer = payload["transformer"]
        self.model = payload["model"]
        self.card = payload["card"]


_bundle: _Bundle | None = None


# ── Rules engine (offline-safe fallback) ─────────────────────────────────
def rules_difficulty(current: str, correct: int, total: int, hints: int) -> tuple[str, float]:  # noqa: E501
    idx = features.difficulty_index(current)
    if total <= 0:
        return current, 1.0
    acc = correct / total
    if acc >= 0.8 and hints <= 1:
        return features.DIFFICULTY_ORDER[min(idx + 1, len(features.DIFFICULTY_ORDER) - 1)], 1.0
    if acc < 0.5 or hints >= 3:
        return features.DIFFICULTY_ORDER[max(idx - 1, 0)], 1.0
    return current, 1.0


def _clamp_one_step(proposed: int, current_idx: int) -> int:
    return max(0, min(len(features.DIFFICULTY_ORDER) - 1,
                      current_idx + (proposed - current_idx) // max(abs(proposed - current_idx), 1)))  # noqa: E501


# ── Model loading / inference ────────────────────────────────────────────
def load_model(model_path: Path | None = None) -> _Bundle | None:
    global _bundle
    if _bundle is not None:
        return _bundle
    path = model_path or config.MODEL_PATH
    if not path.exists():
        return None
    try:
        _bundle = _Bundle(joblib.load(path))
        return _bundle
    except Exception:
        return None


def current_card() -> ModelCard:
    bundle = load_model()
    return bundle.card if bundle else ModelCard(message="No deployed model")


def patient_sample_count(db, patient_id: str) -> int:
    from sqlalchemy import func, select

    from .. import models as m

    return db.scalar(
        select(func.count(m.ActivityRecord.id)).where(
            m.ActivityRecord.patient_account_id == patient_id
        )
    ) or 0


def predict(
    db,
    *,
    patient_id: str,
    category: str,
    current_difficulty: str,
    correct: int,
    total: int,
    hints: int,
    duration_sec: int,
    rules_first: bool = True,
) -> Prediction:
    """Returns the ML suggestion when trustworthy, else the rules engine.

    Trust gates (all must hold for ``source: ml``):
      * a deployed model exists with a passing holdout,
      * the requested category was in the training domains,
      * the patient has enough personal usage to personalize from,
      * the model's confidence clears the threshold AND it stays within one
        step of the current difficulty (gentle transitions for seniors).
    """
    rules_fallback = lambda: Prediction(  # noqa: E731
        *rules_difficulty(current_difficulty, correct, total, hints), source="rules"
    )
    if rules_first:
        rules_decision = rules_difficulty(current_difficulty, correct, total, hints)

    bundle = load_model()
    if bundle is None or not bundle.card.deployed:
        return rules_fallback()
    card = bundle.card
    if category not in card.domains:
        return rules_fallback()
    if patient_sample_count(db, patient_id) < config.MIN_PATIENT_SAMPLES_FOR_PERSONALIZATION:
        return rules_fallback()

    try:
        fv = _request_vector(db, patient_id, category)
        row = features.request_features(
            category=category,
            current_difficulty=current_difficulty,
            correct=correct,
            total=total,
            hints=hints,
            duration_sec=duration_sec,
            domain_slope=fv["domain_slope"],
            days_in_program=fv["days_in_program"],
            hour=fv["hour"],
        )
        x = bundle.transformer.transform(_frame([row]))
        probs = bundle.model.predict_proba(x)[0]
        pred_idx = int(bundle.model.predict(x)[0])
        confidence = float(probs[pred_idx])
        pred = features.DIFFICULTY_ORDER[pred_idx]
    except Exception:
        return rules_fallback()

    # Keep transitions gentle: one step at a time from the current level.
    current_idx = features.difficulty_index(current_difficulty)
    proposed = _clamp_one_step(pred_idx, current_idx)
    actual = features.DIFFICULTY_ORDER[proposed]

    if confidence < 0.55:
        return rules_fallback()
    if rules_first and actual != rules_decision[0] and confidence < 0.70:
        return rules_fallback()
    return Prediction(difficulty=actual, confidence=confidence, source="ml")


def _request_vector(db, patient_id: str, category: str) -> dict:
    from sqlalchemy import select

    rows = db.scalars(
        select(models.ActivityRecord)
        .where(
            models.ActivityRecord.patient_account_id == patient_id,
            models.ActivityRecord.category == category,
        )
        .order_by(models.ActivityRecord.started_at.desc())
        .limit(8)
    ).all()
    ordered = list(reversed(rows))
    recent = [features.accuracy(r.correct, r.total) for r in ordered]
    slope = features._trailing_slope(recent)
    first = db.scalar(
        select(models.ActivityRecord.started_at)
        .where(models.ActivityRecord.patient_account_id == patient_id)
        .order_by(models.ActivityRecord.started_at.asc())
        .limit(1)
    )
    days = max((dt.datetime.utcnow().replace(tzinfo=None) - first).days, 0) if first else 0
    return {
        "domain_slope": slope,
        "days_in_program": days,
        "hour": dt.datetime.now().hour,
    }


def _frame(rows: list[dict]):
    import numpy as np  # type: ignore

    # Columns follow features.FEATURE_COLUMNS order: category then numeric.
    if not rows:
        return np.empty((0, len(features.FEATURE_COLUMNS)), dtype=object)
    return np.array(
        [[r[col] for col in features.FEATURE_COLUMNS] for r in rows],
        dtype=object,
    )