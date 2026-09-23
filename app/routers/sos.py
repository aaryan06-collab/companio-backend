"""SOS alert endpoints: raise, query, acknowledge."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import current_account, linked_patient_ids
from ..schemas import SosAckRequest, SosAlertOut, SosRaiseRequest

router = APIRouter(prefix="/sos", tags=["sos"])

ACTIVE_STATUSES = ("active", "acknowledged")


def _alert_out(db: Session, alert: models.SosAlert) -> SosAlertOut:
    patient = db.get(models.Account, alert.patient_account_id)
    return SosAlertOut(
        id=alert.id,
        patientId=alert.patient_account_id,
        patientName=patient.name if patient else "Patient",
        status=alert.status,
        startedAt=alert.started_at.isoformat(),
        acknowledgedAt=alert.ack_at.isoformat() if alert.ack_at else None,
        acknowledgedBy=alert.acknowledged_by,
    )


@router.post("/raise", response_model=SosAlertOut)
def raise_alert(
    body: SosRaiseRequest,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    if account.role != "patient":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only patient accounts can raise SOS")
    if db.get(models.SosAlert, body.incidentId) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Alert already exists")

    alert = models.SosAlert(
        id=body.incidentId,
        patient_account_id=account.id,
        status="active",
        started_at=datetime.fromisoformat(body.startedAt) if body.startedAt else datetime.utcnow(),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return _alert_out(db, alert)


@router.get("/alerts", response_model=list[SosAlertOut])
def alerts(
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    if account.role == "patient":
        rows = db.scalars(
            select(models.SosAlert)
            .where(
                models.SosAlert.patient_account_id == account.id,
                models.SosAlert.status.in_(ACTIVE_STATUSES),
            )
            .order_by(models.SosAlert.started_at.desc())
        ).all()
        return [_alert_out(db, a) for a in rows]

    patient_ids = linked_patient_ids(db, account.id)
    if not patient_ids:
        return []
    rows = db.scalars(
        select(models.SosAlert)
        .where(
            models.SosAlert.patient_account_id.in_(patient_ids),
            models.SosAlert.status.in_(ACTIVE_STATUSES),
        )
        .order_by(models.SosAlert.started_at.desc())
    ).all()
    return [_alert_out(db, a) for a in rows]


@router.post("/ack", response_model=SosAlertOut)
def ack(
    body: SosAckRequest,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    alert = db.get(models.SosAlert, body.incidentId)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")

    if account.role == "caregiver":
        if alert.patient_account_id not in linked_patient_ids(db, account.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not linked to this patient")
    elif account.role == "patient":
        if alert.patient_account_id != account.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your alert")
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Role cannot acknowledge")

    alert.status = "acknowledged"
    alert.ack_at = alert.ack_at or datetime.utcnow()
    alert.acknowledged_by = account.name
    db.commit()
    db.refresh(alert)

    # Notify the patient device: an inbox record the patient's pull will pick up.
    key = f"sos_ack.{alert.id}"
    if db.get(models.InboxRecord, key) is None:
        caretaker_device = db.scalar(
            select(models.Device).where(models.Device.account_id == account.id)
        )
        db.add(
            models.InboxRecord(
                idempotency_key=key,
                entity_type="sos_ack",
                entity_id=alert.id,
                operation="ack",
                payload_json='{"status":"acknowledged","acknowledgedBy":"'
                + str(account.name)
                + '","acknowledgedAt":"'
                + alert.ack_at.isoformat()
                + '"}',
                patient_id=alert.patient_account_id,
                device_id=caretaker_device.device_id if caretaker_device else "caregiver",
                client_at=alert.ack_at or datetime.utcnow(),
            )
        )
        db.commit()

    return _alert_out(db, alert)