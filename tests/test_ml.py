"""ML module tests: feature building, training gates, union retrain."""

from __future__ import annotations

import os

import pytest

from app import config, models
from app.database import make_session
from app.ml import features, train
from app.ml.service import ModelCard, current_card, predict


def _mk(patient, category, difficulty, correct, total, hints, day):
    return models.ActivityRecord(
        id=f"act.{patient}.{category}.{day}",
        patient_account_id=patient,
        device_id="d",
        activity_id="a",
        category=category,
        difficulty=difficulty,
        started_at=__import__("datetime").datetime(2026, 9, 1 + (day % 20), 9, 0),
        finished_at=__import__("datetime").datetime(2026, 9, 1 + (day % 20), 9, 4),
        completed=True,
        correct=correct,
        total=total,
        hints=hints,
        source="demo",
    )


def _seed_db(path, n=400):
    """Writes n demo records into a fresh train DB so gates pass."""
    url = f"sqlite:///{path}"
    s = make_session(url)
    if s.query(models.ActivityRecord).count() == 0:
        for i in range(n):
            cat = "memory" if i % 2 == 0 else "attention"
            diff = ["gentle", "comfortable", "challenging"][i % 3]
            total = 5
            base_acc = 0.5 + (0.3 if diff == "gentle" else 0.0)
            correct = max(0, min(total, round(total * min(base_acc, 0.95))))
            s.add(_mk("p1", cat, diff, correct, total, i % 3, i))
        s.commit()
    return url


def test_features_row_shape():
    r = _mk("p1", "memory", "gentle", 4, 5, 1, 1)
    fv = features.row_features(r, [r], r.started_at)
    assert fv["category"] == "memory"
    assert 0.0 <= fv["accuracy"] <= 1.0
    assert fv["current_difficulty"] == 0
    assert set(fv) == set(features.FEATURE_COLUMNS)


def test_training_gates_and_union(tmp_path):
    live_path = str(tmp_path / "live.db")
    train_db_url = _seed_db(str(tmp_path / "demo.db"))

    live = make_session(f"sqlite:///{live_path}")
    train_s = make_session(train_db_url)

    # Gates fail with almost no data.
    sparse = make_session("sqlite:///" + str(tmp_path / "sparse.db"))
    summary = train.fit(train_session=sparse, live_session=live, model_path=tmp_path / "m.pkl")
    assert summary.deployed is False
    assert "training skipped" in summary.message

    summary = train.fit(
        train_session=train_s,
        live_session=live,
        model_path=tmp_path / "m.pkl",
    )
    assert summary.deployed is True, summary.message
    assert summary.demoSamples >= 400
    assert summary.realSamples == 0
    assert (tmp_path / "m.pkl").exists()


def test_model_card_and_predict_rules_fallback(tmp_path, monkeypatch):
    from app import config as cfg

    monkeypatch.setattr(cfg, "MODEL_PATH", tmp_path / "nonexistent.pkl")
    card = current_card()
    assert card.deployed is False

    live = make_session("sqlite:///" + str(tmp_path / "live2.db"))
    p = predict(
        live,
        patient_id="p1",
        category="memory",
        current_difficulty="gentle",
        correct=4,
        total=5,
        hints=0,
        duration_sec=120,
    )
    assert p.source == "rules"
    assert p.difficulty == "comfortable"  # 80%+ no hints -> raised by rules