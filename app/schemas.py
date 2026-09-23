"""Pydantic request/response schemas for the Companio API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["patient", "caregiver"]


# ---- Auth ----
class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    role: Role


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterDeviceRequest(BaseModel):
    deviceId: str = Field(min_length=1, max_length=128)
    patientId: str | None = None  # optional server patient account id


class LinkRequest(BaseModel):
    pairingCode: str = Field(min_length=4, max_length=16)
    relationship: str | None = Field(default=None, max_length=64)


class AuthResponse(BaseModel):
    token: str
    accountId: str
    role: Role
    name: str
    pairingCode: str | None = None
    deviceId: str | None = None
    # For caregivers: the patient they currently manage (after linking).
    linkedPatientId: str | None = None
    linkedPatientName: str | None = None
    # For patients: the family caregiver currently looking after them.
    linkedCaregiverName: str | None = None


# ---- Sync ----
class SyncRecord(BaseModel):
    entityType: str
    entityId: str
    operation: str
    payloadJson: str
    idempotencyKey: str
    deviceId: str
    clientAt: str = ""


class SyncPushRequest(BaseModel):
    records: list[SyncRecord]


class SyncPushResponse(BaseModel):
    accepted: list[str]


class SyncPullResponse(BaseModel):
    records: list[SyncRecord]


# ---- SOS ----
class SosRaiseRequest(BaseModel):
    """Retained for a convenience endpoint; the flutter app normally pushes
    a record with entityType ``sos`` instead, so both paths work."""

    incidentId: str
    startedAt: str = ""


class SosAckRequest(BaseModel):
    incidentId: str


class SosAlertOut(BaseModel):
    id: str
    patientId: str
    patientName: str
    status: str
    startedAt: str
    acknowledgedAt: str | None = None
    acknowledgedBy: str | None = None


# ---- Activity / analytics ----
class ActivityBatchRequest(BaseModel):
    records: list[SyncRecord]


class DomainPoint(BaseModel):
    date: str
    attempts: int
    correct: int
    accuracy: float


class DomainSeries(BaseModel):
    category: str
    points: list[DomainPoint]


class EngagementDay(BaseModel):
    date: str
    completed: int
    started: int


class ModelCardOut(BaseModel):
    deployed: bool
    trainedAt: str | None = None
    demoSamples: int = 0
    realSamples: int = 0
    holdoutAccuracy: float | None = None
    baselineAccuracy: float | None = None
    domains: list[str] = []
    message: str = ""


class AnalyticsResponse(BaseModel):
    patientId: str
    patientName: str
    series: list[DomainSeries]
    engagement: list[EngagementDay]
    totalAttempts: int
    completedThisWeek: int
    weekGoal: int
    streakDays: int
    model: ModelCardOut


# â”€â”€ Analytics detail (richer caregiver progress) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class DetailDayPoint(BaseModel):
    date: str
    playMinutes: int
    completed: int
    avgScore: float
    isToday: bool


class DetailToday(BaseModel):
    gamesPlayed: int
    playMinutes: int
    avgScore: float
    improvementPercent: float


class DetailWeek(BaseModel):
    points: list[DetailDayPoint]
    totalMinutes: int
    completedThisWeek: int
    weekGoal: int
    avgScore: float
    improvementPercent: float
    streakDays: int


class DetailGame(BaseModel):
    activityId: str
    category: str
    title: str  # localized title; app falls back to its ActivityCatalog
    playCount: int
    avgScore: float
    bestScore: float
    avgMinutes: float
    lastPlayedAt: str | None
    mostActiveDayKey: str
    mostActiveMinutes: int


class DetailSession(BaseModel):
    activityId: str
    category: str
    activityTitle: str  # localized; app falls back to ActivityCatalog
    startedAt: str
    minutes: int
    score: float
    completed: bool


class DetailSkill(BaseModel):
    category: str
    accuracyPercent: int


class AnalyticsDetailResponse(BaseModel):
    patientId: str
    patientName: str
    range: str
    today: DetailToday
    week: DetailWeek
    games: list[DetailGame] = []
    sessions: list[DetailSession] = []
    skills: list[DetailSkill] = []
    totalAttempts: int


# ---- ML difficulty ----
class NextDifficultyRequest(BaseModel):
    category: str = Field(min_length=1, max_length=32)
    currentDifficulty: str = Field(default="gentle", max_length=16)
    correctCount: int = Field(default=0, ge=0)
    totalCount: int = Field(default=1, ge=1)
    hintCount: int = Field(default=0, ge=0)
    durationSec: int = Field(default=0, ge=0)


class NextDifficultyResponse(BaseModel):
    difficulty: str
    confidence: float
    source: Literal["ml", "rules"]


class TrainResponse(BaseModel):
    deployed: bool
    trainedAt: str | None = None
    demoSamples: int = 0
    realSamples: int = 0
    holdoutAccuracy: float | None = None
    message: str
