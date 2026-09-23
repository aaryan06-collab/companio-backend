"""Detail analytics endpoint tests (richer caregiver progress)."""

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


def test_detail_has_today_week_games_sessions_skills(client, patient_ctx, caregiver_ctx):
    recs = [
        _activity(patient_ctx["accountId"], "memory", "comfortable", 4, 5, 1, "2026-09-19T08:00:00"),
        _activity(patient_ctx["accountId"], "attention", "gentle", 5, 5, 0, "2026-09-19T09:00:00"),
        _activity(patient_ctx["accountId"], "memory", "comfortable", 3, 5, 2, "2026-09-18T10:00:00"),
    ]
    r = _push_many(client, patient_ctx["token"], recs)
    assert r.status_code == 200, r.text

    body = client.get(
        f"/analytics/patient/{patient_ctx['accountId']}/detail",
        headers=_auth(caregiver_ctx["token"]),
    )
    assert body.status_code == 200, body.text
    data = body.json()

    assert data["patientId"] == patient_ctx["accountId"]
    assert data["patientName"] == "Ranu Devi"
    assert data["range"] == "week"
    assert data["totalAttempts"] == 3

    assert set(data["week"].keys()) == {
        "points",
        "totalMinutes",
        "completedThisWeek",
        "weekGoal",
        "avgScore",
        "improvementPercent",
        "streakDays",
    }

    assert set(data["today"].keys()) == {"gamesPlayed", "playMinutes", "avgScore", "improvementPercent"}

    categories = {g["category"] for g in data["games"]}
    assert categories == {"memory", "attention"}
    assert {g["activityId"] for g in data["games"]} == {"act.memory", "act.attention"}

    sessions = data["sessions"]
    assert len(sessions) == 3
    assert {s["category"] for s in sessions} == {"memory", "attention"}

    skills = {s["category"]: s["accuracyPercent"] for s in data["skills"]}
    assert set(skills) >= {"memory", "attention"}


def test_detail_requires_auth(client):
    assert client.get("/analytics/patient/x/detail").status_code == 401


def test_detail_caregiver_not_linked_forbidden(client, patient_ctx):
    other = client.post(
        "/auth/signup",
        json={"username": "stranger2", "password": "secret123", "name": "Stranger", "role": "caregiver"},
    ).json()
    r = client.get(
        f"/analytics/patient/{patient_ctx['accountId']}/detail",
        headers=_auth(other["token"]),
    )
    assert r.status_code == 403
