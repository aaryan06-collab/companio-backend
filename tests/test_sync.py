"""Sync flow tests: idempotency, cross-device delivery, activity ingestion."""

from __future__ import annotations

import json

from conftest import _auth


def _record(entity, entity_id, key, device, op="create", payload=None):
    return {
        "entityType": entity,
        "entityId": entity_id,
        "operation": op,
        "payloadJson": json.dumps(payload or {}),
        "idempotencyKey": key,
        "deviceId": device,
        "clientAt": "2026-09-20T10:00:00",
    }


def test_memory_pushed_by_caregiver_is_pulled_by_patient(client, patient_ctx, caregiver_ctx):
    payload = {
        "patientId": "local-patient-id-1",
        "kind": "text",
        "title": "Bihu night",
        "caption": "We danced together",
        "category": "family",
        "createdBy": "caregiver",
    }
    rec = _record("memory", "mem.1", "pk-mem-1", caregiver_ctx["deviceId"], payload=payload)

    pushed = client.post(
        "/sync/push",
        headers=_auth(caregiver_ctx["token"]),
        json={"records": [rec]},
    )
    assert pushed.status_code == 200
    assert "pk-mem-1" in pushed.json()["accepted"]

    pulled = client.get(
        "/sync/pull",
        headers=_auth(patient_ctx["token"]),
        params={"deviceId": patient_ctx["deviceId"]},
    )
    assert pulled.status_code == 200
    records = pulled.json()["records"]
    assert any(r["idempotencyKey"] == "pk-mem-1" for r in records)
    assert json.loads(records[0]["payloadJson"])["title"] == "Bihu night"


def test_pull_does_not_echo_own_records(client, patient_ctx):
    payload = {"title": "own note", "patientId": "x", "category": "family", "kind": "text"}
    rec = _record("memory", "mem.own", "pk-own", patient_ctx["deviceId"], payload=payload)
    client.post(
        "/sync/push",
        headers=_auth(patient_ctx["token"]),
        json={"records": [rec]},
    )
    pulled = client.get(
        "/sync/pull",
        headers=_auth(patient_ctx["token"]),
        params={"deviceId": patient_ctx["deviceId"]},
    )
    assert all(r["idempotencyKey"] != "pk-own" for r in pulled.json()["records"])


def test_push_is_idempotent(client, patient_ctx):
    rec = _record("memory", "mem.2", "pk-idem", patient_ctx["deviceId"], payload={"title": "t"})
    first = client.post(
        "/sync/push",
        headers=_auth(patient_ctx["token"]),
        json={"records": [rec]},
    )
    second = client.post(
        "/sync/push",
        headers=_auth(patient_ctx["token"]),
        json={"records": [rec]},
    )
    # Retransmission of the same idempotency key is acknowledged, not stored twice.
    assert first.json()["accepted"] == second.json()["accepted"] == ["pk-idem"]

    # A different but registered device sees exactly one copy.
    client.post(
        "/auth/register-device",
        headers=_auth(patient_ctx["token"]),
        json={"deviceId": "patient-phone-2"},
    )
    pulled = client.get(
        "/sync/pull",
        headers=_auth(patient_ctx["token"]),
        params={"deviceId": "patient-phone-2"},
    )
    matches = [r for r in pulled.json()["records"] if r["idempotencyKey"] == "pk-idem"]
    assert len(matches) == 1


def test_activity_records_ingested_for_analytics(client, patient_ctx):
    payload = {
        "activityId": "kitchen_chai",
        "category": "memory",
        "difficulty": "comfortable",
        "startedAt": "2026-09-19T08:30:00",
        "finishedAt": "2026-09-19T08:32:00",
        "completed": True,
        "correct": 4,
        "total": 5,
        "hints": 1,
    }
    rec = _record("activity", "attempt.1", "pk-act-1", patient_ctx["deviceId"], payload=payload)
    r = client.post(
        "/sync/push",
        headers=_auth(patient_ctx["token"]),
        json={"records": [rec]},
    )
    assert "pk-act-1" in r.json()["accepted"]

    analytics = client.get(
        "/analytics/mine",
        headers=_auth(patient_ctx["token"]),
    )
    assert analytics.status_code == 200
    body = analytics.json()
    assert body["totalAttempts"] == 1
    assert any(s["category"] == "memory" for s in body["series"])