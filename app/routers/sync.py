"""Sync endpoints: idempotent push + pull scoped to the calling device's patient."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import current_account, device_for
from ..models import new_id
from ..schemas import (
    ActivityBatchRequest,
    SyncPushRequest,
    SyncPushResponse,
    SyncPullResponse,
    SyncRecord,
)

router = APIRouter(prefix="/sync", tags=["sync"])

PULL_ENTITY_TYPES = ("memory", "contact", "reminder", "sos_ack")


def _parse_ts(raw: str) -> datetime:
    if not raw:
        return datetime.utcnow()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        return datetime.utcnow()


def _record_out(r: models.InboxRecord) -> SyncRecord:
    return SyncRecord(
        entityType=r.entity_type,
        entityId=r.entity_id,
        operation=r.operation,
        payloadJson=r.payload_json,
        idempotencyKey=r.idempotency_key,
        deviceId=r.device_id,
        clientAt=r.client_at.isoformat(),
    )


def _handle_activity(
    db: Session,
    record: SyncRecord,
    patient_id: str,
) -> bool:
    """Routes an ``activity`` record to the analytics table. Returns True if
    the record was newly stored (False = duplicate)."""
    try:
        payload = json.loads(record.payloadJson or "{}")
    except json.JSONDecodeError:
        return False

    record_id = "act." + record.entityId

    # Idempotent by our own record id.
    if db.get(models.ActivityRecord, record_id) is not None:
        return True

    db.add(
        models.ActivityRecord(
            id=record_id,
            patient_account_id=patient_id,
            device_id=record.deviceId,
            activity_id=str(payload.get("activityId") or record.entityId),
            category=str(payload.get("category") or "memory"),
            difficulty=str(payload.get("difficulty") or "gentle"),
            started_at=datetime.fromisoformat(
                str(payload.get("startedAt") or datetime.utcnow().isoformat()).replace("Z", "+00:00")
            )
            .astimezone()
            .replace(tzinfo=None),
            finished_at=(
                datetime.fromisoformat(str(payload["finishedAt"]).replace("Z", "+00:00"))
                .astimezone()
                .replace(tzinfo=None)
                if payload.get("finishedAt")
                else None
            ),
            completed=bool(payload.get("completed", False)),
            correct=int(payload.get("correct", 0) or 0),
            total=int(payload.get("total", 0) or 0),
            hints=int(payload.get("hints", 0) or 0),
            source="real",
        )
    )
    return True


def _handle_sos(
    db: Session,
    record: SyncRecord,
    patient_id: str,
) -> bool:
    """Routes an ``sos`` record to the alert table."""
    try:
        payload = json.loads(record.payloadJson or "{}")
    except json.JSONDecodeError:
        payload = {}

    incident_id = str(payload.get("incidentId") or record.entityId)
    status_value = str(payload.get("status") or "active")

    existing = db.get(models.SosAlert, incident_id)
    if existing is None:
        db.add(
            models.SosAlert(
                id=incident_id,
                patient_account_id=patient_id,
                source_device_id=record.deviceId,
                status="active",
                started_at=_parse_ts(str(payload.get("startedAt") or record.clientAt)),
            )
        )
    else:
        if status_value in ("resolved", "cancelled", "acknowledged"):
            existing.status = status_value
            if status_value in ("resolved", "cancelled"):
                existing.resolved_at = existing.resolved_at or datetime.utcnow()
            if status_value == "acknowledged" and existing.ack_at is None:
                existing.ack_at = datetime.utcnow()
    return True


def _store_inbox(db: Session, record: SyncRecord, patient_id: str) -> bool:
    """Stores a generic inbox record. Already-known idempotency keys are
    acknowledged without re-inserting (idempotent retransmission)."""
    if db.get(models.InboxRecord, record.idempotencyKey) is not None:
        return True
    db.add(
        models.InboxRecord(
            idempotency_key=record.idempotencyKey,
            entity_type=record.entityType,
            entity_id=record.entityId,
            operation=record.operation,
            payload_json=record.payloadJson or "{}",
            patient_id=patient_id,
            device_id=record.deviceId,
            client_at=_parse_ts(record.clientAt),
        )
    )
    return True


def _resolve_patient(db: Session, device_id: str) -> str:
    dev = device_for(db, device_id)
    if dev is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Device is not registered")
    if dev.patient_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Device is not mapped to a patient (patient or linked caregiver)",
        )
    return dev.patient_id


@router.post("/push", response_model=SyncPushResponse)
def push(
    body: SyncPushRequest,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    accepted: list[str] = []
    for record in body.records:
        patient_id = _resolve_patient(db, record.deviceId)
        if record.entityType == "activity":
            ok = _handle_activity(db, record, patient_id)
        elif record.entityType == "sos":
            _handle_sos(db, record, patient_id)
            ok = True
        else:
            ok = _store_inbox(db, record, patient_id)
        if ok:
            accepted.append(record.idempotencyKey)
    db.commit()
    return SyncPushResponse(accepted=accepted)


@router.get("/pull", response_model=SyncPullResponse)
def pull(
    deviceId: str,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
    limit: int = 200,
):
    patient_id = _resolve_patient(db, deviceId)
    dev = device_for(db, deviceId)
    caretaker_id = dev.device_id if dev else deviceId

    rows = db.scalars(
        select(models.InboxRecord)
        .where(
            models.InboxRecord.patient_id == patient_id,
            models.InboxRecord.device_id != caretaker_id,
            models.InboxRecord.entity_type.in_(PULL_ENTITY_TYPES),
        )
        .order_by(models.InboxRecord.created_at.asc())
        .limit(min(limit, 500))
    ).all()

    return SyncPullResponse(records=[_record_out(r) for r in rows])


@router.post("/activity", response_model=SyncPushResponse)
def activity_batch(
    body: ActivityBatchRequest,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    """Convenience bulk endpoint: same treatment as an ``activity`` push."""
    accepted: list[str] = []
    for record in body.records:
        patient_id = _resolve_patient(db, record.deviceId)
        if record.entityType != "activity":
            continue
        if _handle_activity(db, record, patient_id):
            accepted.append(record.idempotencyKey)
    db.commit()
    return SyncPushResponse(accepted=accepted)