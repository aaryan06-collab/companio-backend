"""Auth endpoints: signup, login, device registration, caregiver linking."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import current_account
from ..models import generate_pairing_code, new_id
from ..schemas import AuthResponse, LinkRequest, LoginRequest, RegisterDeviceRequest, SignupRequest
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _account_response(db: Session, account: models.Account) -> AuthResponse:
    pairing = None
    linked_patient_id = None
    linked_patient_name = None
    linked_caregiver_name = None
    if account.role == "patient" and account.profile:
        pairing = account.profile.pairing_code
        link = db.scalar(
            select(models.CaregiverLink)
            .where(models.CaregiverLink.patient_account_id == account.id)
            .order_by(models.CaregiverLink.created_at.desc())
        )
        if link is not None:
            caregiver = db.get(models.Account, link.caregiver_account_id)
            if caregiver is not None:
                linked_caregiver_name = caregiver.name
    elif account.role == "caregiver":
        link = db.scalar(
            select(models.CaregiverLink)
            .where(models.CaregiverLink.caregiver_account_id == account.id)
            .order_by(models.CaregiverLink.created_at.desc())
        )
        if link is not None:
            linked_patient_id = link.patient_account_id
            patient = db.get(models.Account, link.patient_account_id)
            if patient is not None:
                linked_patient_name = patient.name
    return AuthResponse(
        token=create_token(account.id, account.role),
        accountId=account.id,
        role=account.role,
        name=account.name,
        pairingCode=pairing,
        linkedPatientId=linked_patient_id,
        linkedPatientName=linked_patient_name,
        linkedCaregiverName=linked_caregiver_name,
    )


@router.post("/signup", response_model=AuthResponse)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    exists = db.scalar(select(models.Account).where(models.Account.username == body.username))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")

    account = models.Account(
        id=new_id("acct"),
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        name=body.name,
    )
    db.add(account)
    db.flush()

    if body.role == "patient":
        code = generate_pairing_code()
        while db.scalar(select(models.PatientProfile).where(models.PatientProfile.pairing_code == code)):
            code = generate_pairing_code()
        db.add(
            models.PatientProfile(
                account_id=account.id,
                display_name=body.name,
                pairing_code=code,
            )
        )

    db.commit()
    db.refresh(account)
    return _account_response(db, account)


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    account = db.scalar(select(models.Account).where(models.Account.username == body.username))
    if account is None or not verify_password(body.password, account.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")
    return _account_response(db, account)


@router.post("/register-device", response_model=AuthResponse)
def register_device(
    body: RegisterDeviceRequest,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    existing = db.scalar(select(models.Device).where(models.Device.device_id == body.deviceId))
    if existing is not None:
        existing.account_id = account.id
        if body.patientId:
            existing.patient_id = body.patientId
        elif account.role == "patient":
            existing.patient_id = account.id
        db.commit()
    else:
        patient_id = body.patientId
        if patient_id is None and account.role == "patient":
            patient_id = account.id
        db.add(
            models.Device(
                id=new_id("dev"),
                device_id=body.deviceId,
                account_id=account.id,
                patient_id=patient_id,
            )
        )
        db.commit()

    return _account_response(db, account)


@router.post("/link", response_model=AuthResponse)
def link(
    body: LinkRequest,
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    if account.role != "caregiver":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only caregivers can link to a patient")

    profile = db.scalar(
        select(models.PatientProfile).where(models.PatientProfile.pairing_code == body.pairingCode.upper())
    )
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pairing code not found")

    patient = db.get(models.Account, profile.account_id)
    if patient is None or patient.role != "patient":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pairing code not found")

    link = db.scalar(
        select(models.CaregiverLink).where(
            models.CaregiverLink.caregiver_account_id == account.id,
            models.CaregiverLink.patient_account_id == patient.id,
        )
    )
    if link is None:
        db.add(
            models.CaregiverLink(
                id=new_id("link"),
                caregiver_account_id=account.id,
                patient_account_id=patient.id,
                relationship=body.relationship,
            )
        )
        db.commit()

    return _account_response(db, account)


@router.get("/me", response_model=AuthResponse)
def me(
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    return _account_response(db, account)