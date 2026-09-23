"""Auth flow tests: signup, login, device registration, caregiver linking."""

from __future__ import annotations

from conftest import _auth


def test_signup_patient_gets_pairing_code(client):
    r = client.post(
        "/auth/signup",
        json={"username": "asha", "password": "secret123", "name": "Asha", "role": "patient"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "patient"
    assert len(body["pairingCode"]) == 6
    assert body["token"]


def test_login_valid_and_invalid(client, patient_ctx):
    ok = client.post("/auth/login", json={"username": "ranu", "password": "secret123"})
    assert ok.status_code == 200
    assert ok.json()["token"]

    bad = client.post("/auth/login", json={"username": "ranu", "password": "wrong"})
    assert bad.status_code == 401


def test_double_signup_conflict(client):
    r = client.post(
        "/auth/signup",
        json={"username": "tester01", "password": "secret123", "name": "T", "role": "patient"},
    )
    assert r.status_code == 200
    r2 = client.post(
        "/auth/signup",
        json={"username": "tester01", "password": "secret123", "name": "T", "role": "patient"},
    )
    assert r2.status_code == 409


def test_unregistered_device_cannot_push(client, patient_ctx):
    r = client.post(
        "/sync/push",
        headers=_auth(patient_ctx["token"]),
        json={"records": []},
    )
    assert r.json()["accepted"] == []
    # Unknown device id should 401.
    r2 = client.post(
        "/sync/push",
        headers=_auth(patient_ctx["token"]),
        json={
            "records": [
                {
                    "entityType": "memory",
                    "entityId": "m1",
                    "operation": "create",
                    "payloadJson": "{}",
                    "idempotencyKey": "k1",
                    "deviceId": "unknown-phone",
                    "clientAt": "",
                }
            ]
        },
    )
    assert r2.status_code == 401


def test_caregiver_link_requires_caregiver(client, patient_ctx):
    # Patient cannot link.
    r = client.post(
        "/auth/link",
        headers=_auth(patient_ctx["token"]),
        json={"pairingCode": patient_ctx["pairingCode"]},
    )
    assert r.status_code == 403


def test_caregiver_gets_linked_patient_on_response(client, patient_ctx):
    r = client.post(
        "/auth/signup",
        json={"username": "kiran", "password": "secret123", "name": "Kiran", "role": "caregiver"},
    )
    assert r.status_code == 200
    token = r.json()["token"]

    r2 = client.post(
        "/auth/link",
        headers=_auth(token),
        json={"pairingCode": patient_ctx["pairingCode"], "relationship": "daughter"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["linkedPatientId"] == patient_ctx["accountId"]
    assert body["linkedPatientName"] == "Ranu Devi"

    # The link is reflected on later logins / /me too.
    r3 = client.post("/auth/login", json={"username": "kiran", "password": "secret123"})
    assert r3.json()["linkedPatientId"] == patient_ctx["accountId"]
    r4 = client.get("/auth/me", headers=_auth(token))
    assert r4.json()["linkedPatientName"] == "Ranu Devi"


def test_patient_gets_linked_caregiver_name(client, patient_ctx):
    r = client.post(
        "/auth/signup",
        json={"username": "arun", "password": "secret123", "name": "Arun", "role": "caregiver"},
    )
    assert r.status_code == 200
    token = r.json()["token"]

    r2 = client.post(
        "/auth/link",
        headers=_auth(token),
        json={"pairingCode": patient_ctx["pairingCode"], "relationship": "son"},
    )
    assert r2.status_code == 200

    r3 = client.post("/auth/login", json={"username": "ranu", "password": "secret123"})
    assert r3.status_code == 200
    assert r3.json()["linkedCaregiverName"] == "Arun"

    r4 = client.get("/auth/me", headers=_auth(patient_ctx["token"]))
    assert r4.json()["linkedCaregiverName"] == "Arun"