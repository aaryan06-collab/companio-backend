"""Analytics endpoints: cognitive performance trends + engagement."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import current_account, linked_patient_ids
from ..ml.service import current_card
from ..schemas import (
    AnalyticsDetailResponse,
    AnalyticsResponse,
    DetailDayPoint,
    DetailGame,
    DetailSession,
    DetailSkill,
    DetailToday,
    DetailWeek,
    DomainPoint,
    DomainSeries,
    EngagementDay,
    ModelCardOut,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _resolve_patient(db: Session, account: models.Account, patient_id: str | None) -> models.Account:
    target_id = patient_id or account.id
    if account.role == "caregiver":
        if target_id not in linked_patient_ids(db, account.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not linked to this patient")
    elif account.role == "patient":
        if target_id != account.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your data")
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Role cannot view analytics")
    patient = db.get(models.Account, target_id)
    if patient is None or patient.role != "patient":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
    return patient


def _rows_for(db: Session, patient_id: str) -> list[models.ActivityRecord]:
    return db.scalars(
        select(models.ActivityRecord)
        .where(models.ActivityRecord.patient_account_id == patient_id)
        .order_by(models.ActivityRecord.started_at.asc())
    ).all()


def _streak_days(completed_by_day: set[str]) -> int:
    """Consecutive days with >=1 completed activity, ending today or yesterday."""
    today = date.today()
    streak = 0
    day = today
    if day.isoformat() not in completed_by_day:
        day = day - timedelta(days=1)
    while day.isoformat() in completed_by_day:
        streak += 1
        day = day - timedelta(days=1)
    return streak


@router.get("/mine", response_model=AnalyticsResponse)
def mine(account: models.Account = Depends(current_account), db: Session = Depends(get_db)):
    return _build(db, account, patient_id=account.id)


@router.get("/patient/{patient_id}", response_model=AnalyticsResponse)
def for_patient(
    patient_id: str,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    return _build(db, account, patient_id=patient_id)


@router.get("/patient/{patient_id}/detail", response_model=AnalyticsDetailResponse)
def detail_for_patient(
    patient_id: str,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
    period: str = Query(default="week", alias="range"),
):
    return _build_detail(db, account, patient_id=patient_id, period=period)


def _build_detail(
    db: Session, account: models.Account, patient_id: str, period: str
) -> AnalyticsDetailResponse:
    patient = _resolve_patient(db, account, patient_id)
    rows = _rows_for(db, patient.id)

    today = date.today()
    span = [(today - timedelta(days=i)) for i in range(6, -1, -1)]

    per_day_minutes: dict[date, int] = defaultdict(int)
    per_day_completed: dict[date, int] = defaultdict(int)
    per_day_score: dict[date, list[float]] = defaultdict(list)
    by_game: dict[str, list[models.ActivityRecord]] = defaultdict(list)
    by_category: dict[str, list[models.ActivityRecord]] = defaultdict(list)
    sessions: list[DetailSession] = []
    completed_days: set[str] = set()

    for r in rows:
        d = r.started_at.date()
        minutes = _minutes(r)
        score = _score_percent(r)
        per_day_minutes[d] += minutes
        per_day_score[d].append(score)
        if r.completed:
            per_day_completed[d] += 1
            completed_days.add(str(d))
        by_game[r.activity_id].append(r)
        by_category[r.category].append(r)
        sessions.append(
            DetailSession(
                activityId=r.activity_id,
                category=r.category,
                activityTitle=r.activity_id,
                startedAt=r.started_at.isoformat() + "Z",
                minutes=minutes,
                score=score,
                completed=r.completed,
            )
        )

    points: list[DetailDayPoint] = []
    for d in span:
        day_scores = per_day_score[d]
        points.append(
            DetailDayPoint(
                date=d.isoformat(),
                playMinutes=per_day_minutes[d],
                completed=per_day_completed[d],
                avgScore=_avg(day_scores),
                isToday=d == today,
            )
        )

    week_scores = [s for d in span for s in per_day_score[d]]
    prev_span = [(today - timedelta(days=i)) for i in range(13, 6, -1)]
    prev_scores = [s for d in prev_span for s in per_day_score[d]]
    prev_avg = _avg(prev_scores)
    week_avg = _avg(week_scores)
    improvement = _improvement(week_avg, prev_avg)

    today_scores = per_day_score[today]
    day_improvement = 0.0
    if today_scores:
        yesterday = today - timedelta(days=1)
        yesterday_scores = per_day_score[yesterday]
        day_improvement = _improvement(_avg(today_scores), _avg(yesterday_scores))

    games: list[DetailGame] = []
    for activity_id, game_rows in sorted(by_game.items()):
        scores = [_score_percent(r) for r in game_rows]
        per_day: dict[date, int] = defaultdict(int)
        for r in game_rows:
            per_day[r.started_at.date()] += _minutes(r)
        most_active = max(per_day, key=per_day.get) if per_day else today
        games.append(
            DetailGame(
                activityId=activity_id,
                category=game_rows[0].category,
                title=game_rows[0].activity_id,
                playCount=len(game_rows),
                avgScore=_avg(scores),
                bestScore=max(scores) if scores else 0.0,
                avgMinutes=_avg([_minutes(r) for r in game_rows]),
                lastPlayedAt=max(
                    (r.finished_at or r.started_at).isoformat() + "Z"
                    for r in game_rows
                ),
                mostActiveDayKey=most_active.isoformat(),
                mostActiveMinutes=per_day[most_active],
            )
        )

    skills: list[DetailSkill] = []
    for category, cat_rows in sorted(by_category.items()):
        skills.append(
            DetailSkill(
                category=category,
                accuracyPercent=round(
                    _avg([_score_percent(r) for r in cat_rows])
                ),
            )
        )

    sessions.sort(key=lambda s: s.startedAt, reverse=True)

    return AnalyticsDetailResponse(
        patientId=patient.id,
        patientName=patient.name,
        range=period,
        today=DetailToday(
            gamesPlayed=sum(
                1 for r in rows if r.started_at.date() == today
            ),
            playMinutes=per_day_minutes[today],
            avgScore=_avg(today_scores),
            improvementPercent=day_improvement,
        ),
        week=DetailWeek(
            points=points,
            totalMinutes=sum(per_day_minutes[d] for d in span),
            completedThisWeek=sum(per_day_completed[d] for d in span),
            weekGoal=7,
            avgScore=week_avg,
            improvementPercent=improvement,
            streakDays=_streak_days(completed_days),
        ),
        games=games,
        sessions=sessions,
        skills=skills,
        totalAttempts=len(rows),
    )


def _minutes(r: models.ActivityRecord) -> int:
    if r.finished_at and r.started_at:
        elapsed = (r.finished_at - r.started_at).total_seconds() / 60.0
        return max(0, round(elapsed))
    return 0


def _score_percent(r: models.ActivityRecord) -> float:
    if not r.total:
        return 0.0
    return round(100.0 * r.correct / r.total, 2)


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _improvement(current: float, previous: float) -> float:
    if not previous:
        return 0.0
    return round(100.0 * (current - previous) / previous, 2)


def _build(db: Session, account: models.Account, patient_id: str) -> AnalyticsResponse:
    patient = _resolve_patient(db, account, patient_id)
    rows = _rows_for(db, patient.id)

    by_category: dict[str, list[models.ActivityRecord]] = defaultdict(list)
    completed_on: dict[date, int] = defaultdict(int)
    started_on: dict[date, int] = defaultdict(int)
    completed_days: set[str] = set()

    for r in rows:
        by_category[r.category].append(r)
        started_on[r.started_at.date()] += 1
        if r.completed:
            completed_on[r.started_at.date()] += 1
            completed_days.add(r.started_at.date().isoformat())

    today = date.today()
    span = [(today - timedelta(days=i)) for i in range(13, -1, -1)]

    series: list[DomainSeries] = []
    for category, cat_rows in sorted(by_category.items()):
        per_day = defaultdict(lambda: [0, 0])
        for r in cat_rows:
            cell = per_day[r.started_at.date()]
            cell[0] += 1
            cell[1] += r.correct
        points: list[DomainPoint] = []
        for d in span:
            attempts, correct = per_day[d]
            points.append(
                DomainPoint(
                    date=d.isoformat(),
                    attempts=attempts,
                    correct=correct,
                    accuracy=(correct / attempts if attempts else 0.0),
                )
            )
        series.append(DomainSeries(category=category, points=points))

    engagement = [
        EngagementDay(date=d.isoformat(), completed=completed_on.get(d, 0), started=started_on.get(d, 0))
        for d in span
    ]

    week_start = today - timedelta(days=7)
    completed_this_week = sum(c for d, c in completed_on.items() if d >= week_start)

    card = current_card()
    model_out = ModelCardOut(
        deployed=card.deployed,
        trainedAt=card.trainedAt,
        demoSamples=card.demoSamples,
        realSamples=card.realSamples,
        holdoutAccuracy=card.holdoutAccuracy,
        baselineAccuracy=card.baselineAccuracy,
        domains=card.domains,
        message=card.message,
    )

    return AnalyticsResponse(
        patientId=patient.id,
        patientName=patient.name,
        series=series,
        engagement=engagement,
        totalAttempts=len(rows),
        completedThisWeek=completed_this_week,
        weekGoal=7,
        streakDays=_streak_days(completed_days),
        model=model_out,
    )