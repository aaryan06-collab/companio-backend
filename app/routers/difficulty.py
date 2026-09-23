"""Adaptive difficulty endpoint: fuses the ML model with the rules engine."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import models
from ..database import get_db
from ..deps import current_account
from ..ml import features, service
from ..schemas import NextDifficultyRequest, NextDifficultyResponse
from sqlalchemy.orm import Session

router = APIRouter(prefix="/difficulty", tags=["difficulty"])


@router.post("/next", response_model=NextDifficultyResponse)
def next_difficulty(
    body: NextDifficultyRequest,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    context = service._request_vector(db, account.id, body.category)
    prediction = service.predict(
        db,
        patient_id=account.id,
        category=body.category,
        current_difficulty=body.currentDifficulty,
        correct=body.correctCount,
        total=body.totalCount,
        hints=body.hintCount,
        duration_sec=body.durationSec,
    )
    return NextDifficultyResponse(
        difficulty=prediction.difficulty,
        confidence=round(prediction.confidence, 4),
        source=prediction.source,
    )