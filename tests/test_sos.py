"""SOS alert flow tests: raise (via sync), caregiver view, ack."""

from __future__ import annotations

import json

from conftest import _auth


def test_sos_lifecycle(client, patient_ctx, caregiver_ctx):
    # Patient pushes an SOS record through the sync pipeline.
    payload = {"incidentId": "incident.1", "status": "active", "startedAt": "2026-09-20T09:00:00"}
    rec = {
        "entityType": "sos",
        "entityId": "incident.1",
        "operation": "raise",
        "payloadJson": json.dumps(payload),
        "idempotencyKey": "pk-sos-1",
        "deviceId": patient_ctx["deviceId"],
        "clientAt": "2026-09-20T09:00:00",
    }
    r = client.post(
        "/sync/push",
        headers=_auth(patient_ctx["token"]),
        json={"records": [rec]},
    )
    assert r.status_code == 200
    assert "pk-sos-1" in r.json()["accepted"]

    # Caregiver sees the active alert.
    alerts = client.get("/sos/alerts", headers=_auth(caregiver_ctx["token"]))
    assert alerts.status_code == 200
    items = alerts.json()
    assert len(items) == 1
    assert items[0]["id"] == "incident.1"
    assert items[0]["status"] == "active"
    assert items[0]["patientName"] == "Ranu Devi"

    # Patient also sees it.
    mine = client.get("/sos/alerts", headers=_auth(patient_ctx["token"]))
    assert len(mine.json()) == 1

    # Caregiver acknowledges.
    ack = client.post(
        "/sos/ack",
        headers=_auth(caregiver_ctx["token"]),
        json={"incidentId": "incident.1"},
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"
    assert ack.json()["acknowledgedBy"] == "Babu Ram"

    # Still visible until resolved, now marked acknowledged (so a caregiver
    # dashboard can keep showing the alert until the case closes).
    alerts2 = client.get("/sos/alerts", headers=_auth(caregiver_ctx["token"]))
    assert len(alerts2.json()) == 1
    assert alerts2.json()[0]["status"] == "acknowledged"
    assert alerts2.json()[0]["acknowledgedBy"] == "Babu Ram"

    # The patient device learns about the ack on its next pull.
    pull = client.get(
        "/sync/pull",
        headers=_auth(patient_ctx["token"]),
        params={"deviceId": patient_ctx["deviceId"]},
    )
    ack_records = [r for r in pull.json()["records"] if r["entityType"] == "sos_ack"]
    assert len(ack_records) == 1
    assert ack_records[0]["entityId"] == "incident.1"
    assert ack_records[0]["payloadJson"] != ""


def test_caregiver_cannot_ack_unlinked_patient(client, caregiver_ctx):
    r = client.post(
        "/sos/ack",
        headers=_auth(caregiver_ctx["token"]),
        json={"incidentId": "does-not-exist"},
    )
    assert r.status_code == 404