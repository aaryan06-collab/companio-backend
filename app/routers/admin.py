"""Admin endpoints: retrain the model, inspect training status."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import config
from ..database import get_db, make_session
from ..ml import train as ml_train
from ..ml.service import current_card
from ..schemas import ModelCardOut, TrainResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/retrain", response_model=TrainResponse)
def retrain(_: object = Depends(get_db)):
    summary = ml_train.fit(
        train_session=make_session(config.TRAIN_DATABASE_URL),
        live_session=make_session(config.DATABASE_URL),
        model_path=config.MODEL_PATH,
        include_demo=True,
    )
    return TrainResponse(
        deployed=summary.deployed,
        trainedAt=summary.trainedAt,
        demoSamples=summary.demoSamples,
        realSamples=summary.realSamples,
        holdoutAccuracy=summary.holdoutAccuracy,
        message=summary.message,
    )


@router.get("/model-card", response_model=ModelCardOut)
def model_card(_: object = Depends(get_db)):
    card = current_card()
    return ModelCardOut(
        deployed=card.deployed,
        trainedAt=card.trainedAt,
        demoSamples=card.demoSamples,
        realSamples=card.realSamples,
        holdoutAccuracy=card.holdoutAccuracy,
        baselineAccuracy=card.baselineAccuracy,
        domains=card.domains,
        message=card.message,
    )


@router.get("/status", response_model=dict)
def status(_: object = Depends(get_db)):
    live = make_session(config.DATABASE_URL)
    train = make_session(config.TRAIN_DATABASE_URL)
    from sqlalchemy import func, select

    from .. import models as m

    def count(s, model):
        return s.scalar(select(func.count()).select_from(model)) or 0

    return {
        "live_db": {
            "path": config.DATABASE_URL,
            "accounts": count(live, m.Account),
            "activity_records": count(live, m.ActivityRecord),
            "inbox_records": count(live, m.InboxRecord),
            "sos_alerts": count(live, m.SosAlert),
        },
        "train_db": {
            "path": config.TRAIN_DATABASE_URL,
            "activity_records": count(train, m.ActivityRecord),
        },
        "model": config.MODEL_PATH.name,
    }