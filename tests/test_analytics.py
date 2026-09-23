"""Analytics + difficulty endpoint tests."""

from __future__ import annotations

import json

from conftest import _auth


def _activity(pid, cat, difficulty, correct, total, hints, started):
    return {
        "entityType": "activity",
        "entityId": f"a.{pid}.{cat}.{started}",
        "operation": "create",
        "payloadJson": json.dumps(
            {
                "activityId": f"act.{cat}",
                "category": cat,
                "difficulty": difficulty,
                "startedAt": started,
                "finishedAt": started,
                "completed": True,
                "correct": correct,
                "total": total,
                "hints": hints,
            }
        ),
        "idempotencyKey": f"pk.{pid}.{cat}.{started}",
        "deviceId": "patient-phone-1",
        "clientAt": started,
    }


def _push_many(client, token, records):
    return client.post(
        "/sync/push",
        headers=_auth(token),
        json={"records": records},
    )


def test_analytics_for_caregiver_of_linked_patient(client, patient_ctx, caregiver_ctx):
    recs = [
        _activity(1, "memory", "comfortable", 4, 5, 1, "2026-09-19T08:00:00"),
        _activity(2, "attention", "gentle", 5, 5, 0, "2026-09-19T09:00:00"),
        _activity(3, "memory", "comfortable", 3, 5, 2, "2026-09-18T10:00:00"),
    ]
    _push_many(client, patient_ctx["token"], recs)

    body = client.get(
        f"/analytics/patient/{patient_ctx['accountId']}",
        headers=_auth(caregiver_ctx["token"]),
    )
    assert body.status_code == 200
    data = body.json()
    assert data["totalAttempts"] == 3
    categories = {s["category"] for s in data["series"]}
    assert categories == {"memory", "attention"}
    assert data["patientName"] == "Ranu Devi"

    # Unlinked caregiver is forbidden.
    other = client.post(
        "/auth/signup",
        json={"username": "stranger", "password": "secret123", "name": "S", "role": "caregiver"},
    ).json()
    blocked = client.get(
        f"/analytics/patient/{patient_ctx['accountId']}",
        headers=_auth(other["token"]),
    )
    assert blocked.status_code == 403


def test_difficulty_rules_fallback_when_patient_underrepresented(client, patient_ctx):
    r = client.post(
        "/difficulty/next",
        headers=_auth(patient_ctx["token"]),
        json={
            "category": "memory",
            "currentDifficulty": "gentle",
            "correctCount": 1,
            "totalCount": 2,
            "hintCount": 1,
            "durationSec": 90,
        },
    )
    assert r.status_code == 200
    body = r.json()
    # A brand-new patient with < the personalization minimum gets rules.
    assert body["source"] == "rules"
    assert body["difficulty"] == "gentle"


def test_analytics_requires_auth(client):
    assert client.get("/analytics/mine").status_code == 401