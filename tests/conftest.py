"""Pytest fixtures. Keep DBs isolated: env must be set BEFORE importing `app`."""

from __future__ import annotations

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="companio-test-")
os.environ["MINDCARE_LIVE_DB"] = f"sqlite:///{_tmp}/live.db"
os.environ["MINDCARE_TRAIN_DB"] = f"sqlite:///{_tmp}/demo.db"
os.environ["MINDCARE_MODEL_PATH"] = f"{_tmp}/test_model.pkl"
os.environ["MINDCARE_MEDIA_DIR"] = f"{_tmp}/media"
os.environ["MINDCARE_JWT_SECRET"] = "test-secret-not-for-prod"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.database import init_db, make_session  # noqa: E402
from app import models  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    init_db()
    yield


@pytest.fixture(autouse=True)
def _fresh_db():
    """Give every test a clean live database (schema dropped + recreated)."""
    yield
    s = make_session(os.environ["MINDCARE_LIVE_DB"])
    models.Base.metadata.drop_all(s.bind)
    models.Base.metadata.create_all(s.bind)
    s.close()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def patient_ctx(client) -> dict:
    """Patient account + registered device."""
    r = client.post(
        "/auth/signup",
        json={"username": "ranu", "password": "secret123", "name": "Ranu Devi", "role": "patient"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    token = body["token"]

    r2 = client.post(
        "/auth/register-device",
        headers=_auth(token),
        json={"deviceId": "patient-phone-1"},
    )
    assert r2.status_code == 200, r2.text
    return {
        "accountId": body["accountId"],
        "token": token,
        "deviceId": "patient-phone-1",
        "pairingCode": body["pairingCode"],
    }


@pytest.fixture
def caregiver_ctx(client, patient_ctx) -> dict:
    """Caregiver account linked to the patient's device."""
    r = client.post(
        "/auth/signup",
        json={"username": "babu", "password": "secret123", "name": "Babu Ram", "role": "caregiver"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    r2 = client.post(
        "/auth/link",
        headers=_auth(token),
        json={"pairingCode": patient_ctx["pairingCode"], "relationship": "son"},
    )
    assert r2.status_code == 200, r2.text

    r3 = client.post(
        "/auth/register-device",
        headers=_auth(token),
        json={"deviceId": "caregiver-phone-1", "patientId": patient_ctx["accountId"]},
    )
    assert r3.status_code == 200, r3.text
    return {
        "accountId": r.json()["accountId"],
        "token": token,
        "deviceId": "caregiver-phone-1",
    }