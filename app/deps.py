"""Shared FastAPI dependencies: authentication + helpers."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import get_db
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


def current_account(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> models.Account:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    try:
        payload = decode_token(creds.credentials)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc
    account = db.get(models.Account, payload.get("sub"))
    if account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown account")
    return account


def require_role(role: str):
    def checker(account: models.Account = Depends(current_account)) -> models.Account:
        if account.role != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {role}")
        return account

    return checker


def device_for(db: Session, device_id: str) -> models.Device | None:
    return db.scalar(select(models.Device).where(models.Device.device_id == device_id))


def patient_for_device(db: Session, device_id: str) -> models.Device | None:
    dev = device_for(db, device_id)
    if dev is None or dev.patient_id is None:
        return None
    return dev


def linked_patient_ids(db: Session, caregiver_account_id: str) -> list[str]:
    links = db.scalars(
        select(models.CaregiverLink).where(
            models.CaregiverLink.caregiver_account_id == caregiver_account_id
        )
    ).all()
    return [link.patient_account_id for link in links]