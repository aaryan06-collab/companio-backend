"""End-to-end smoke test for the Companio SIH demo using a real HTTP server.

Replays the two-device flow exactly the way the Flutter app drives it:

  Patient phone     : signup -> register-device -> push activity + SOS records
  Caregiver phone   : signup -> link (pairing code) -> register-device
  Caregiver phone   : sees the live SOS alert -> acknowledges it
  Patient phone     : pull picks up the sos_ack inbox record
  Caregiver phone   : analytics for the linked patient + adaptive difficulty

The server is started on a throwaway port with temporary databases so the
real ``data/`` dir is never touched. Runs on the stock Python stdlib.

Usage:
    python scripts\\demo_e2e.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
SERVER_DIR = Path(__file__).resolve().parent.parent

FAILED: list[str] = []
STEP_COUNT = [0]


def check(step: str, ok: bool, detail: str = "") -> None:
    STEP_COUNT[0] += 1
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {step}"
    if detail:
        line += f" | {detail}"
    print(line)
    if not ok:
        FAILED.append(step)


def call(method: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_text": e.read().decode(errors="replace")}


def wait_server() -> bool:
    for _ in range(60):
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2) as resp:
                return resp.status == 200
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.5)
    return False


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="companio-e2e-")
    env = os.environ.copy()
    env["MINDCARE_LIVE_DB"] = f"sqlite:///{tmp}/live.db"
    env["MINDCARE_TRAIN_DB"] = f"sqlite:///{tmp}/demo.db"
    env["MINDCARE_MODEL_PATH"] = str(Path(tmp) / "model.pkl")

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=SERVER_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        check("server boots", wait_server())
        if not wait_server():
            return 1

        now = datetime.now(timezone.utc).isoformat()

        # ── Patient phone ────────────────────────────────────────────────
        p_signup = call("POST", "/auth/signup", body={
            "username": f"e2e_patient_{int(time.time())}",
            "password": "secret123",
            "name": "Ranu Devi",
            "role": "patient",
        })
        check("patient signup", "token" in p_signup and p_signup.get("pairingCode"),
              f"pairing={p_signup.get('pairingCode')}")
        p_token = p_signup.get("token")
        p_acct = p_signup.get("accountId")
        pairing = p_signup.get("pairingCode")

        p_dev = call("POST", "/auth/register-device", token=p_token,
                     body={"deviceId": "e2e-patient-phone"})
        check("patient register-device", p_dev.get("accountId") == p_acct)

        activity_records = []
        for i, cat in enumerate(("memory", "attention")):
            activity_records.append({
                "entityType": "activity",
                "entityId": f"act-e2e-{i}",
                "operation": "upsert",
                "payloadJson": json.dumps({
                    "activityId": f"demo_{cat}_{i}",
                    "category": cat,
                    "difficulty": "gentle",
                    "startedAt": now,
                    "finishedAt": now,
                    "completed": True,
                    "correct": 3,
                    "total": 4,
                    "hints": 0,
                }),
                "idempotencyKey": f"e2e-activity-{i}",
                "deviceId": "e2e-patient-phone",
                "clientAt": now,
            })
        push = call("POST", "/sync/push", token=p_token,
                    body={"records": activity_records})
        check("patient pushes activity records",
              push.get("accepted") == ["e2e-activity-0", "e2e-activity-1"])

        sos_records = [{
            "entityType": "sos",
            "entityId": "e2e-sos-1",
            "operation": "create",
            "payloadJson": json.dumps({
                "incidentId": "e2e-sos-1",
                "status": "active",
                "startedAt": now,
            }),
            "idempotencyKey": "e2e-sos-1",
            "deviceId": "e2e-patient-phone",
            "clientAt": now,
        }]
        push_sos = call("POST", "/sync/push", token=p_token, body={"records": sos_records})
        check("patient pushes SOS record", push_sos.get("accepted") == ["e2e-sos-1"])

        # ── Caregiver phone ──────────────────────────────────────────────
        c_signup = call("POST", "/auth/signup", body={
            "username": f"e2e_caregiver_{int(time.time())}",
            "password": "secret123",
            "name": "Babu Ram",
            "role": "caregiver",
        })
        check("caregiver signup", "token" in c_signup)
        c_token = c_signup.get("token")

        link = call("POST", "/auth/link", token=c_token,
                    body={"pairingCode": pairing, "relationship": "son"})
        check("caregiver links via pairing code",
              link.get("linkedPatientId") == p_acct
              and link.get("linkedPatientName") == "Ranu Devi",
              f"linked={link.get('linkedPatientName')}")

        call("POST", "/auth/register-device", token=c_token,
             body={"deviceId": "e2e-caregiver-phone", "patientId": p_acct})

        alerts = call("GET", "/sos/alerts", token=c_token)
        check("caregiver sees live SOS alert",
              any(a.get("id") == "e2e-sos-1" and a.get("status") == "active"
                  for a in alerts))

        ack = call("POST", "/sos/ack", token=c_token, body={"incidentId": "e2e-sos-1"})
        check("caregiver acknowledges SOS",
              ack.get("status") == "acknowledged" and ack.get("acknowledgedBy") == "Babu Ram")

        # ── Patient phone pull ───────────────────────────────────────────
        pull = call("GET", "/sync/pull?deviceId=e2e-patient-phone", token=p_token)
        acks = [r for r in pull.get("records", []) if r.get("entityType") == "sos_ack"]
        check("patient pull receives sos_ack",
              any(r.get("entityId") == "e2e-sos-1" for r in acks),
              f"records={[r.get('entityId') for r in pull.get('records', [])]}")

        # ── Caregiver analytics + adaptive difficulty ────────────────────
        analytics = call("GET", f"/analytics/patient/{p_acct}", token=c_token)
        check("caregiver reads patient analytics",
              analytics.get("patientId") == p_acct
              and analytics.get("totalAttempts") == 2
              and len(analytics.get("series", [])) == 2,
              f"attempts={analytics.get('totalAttempts')}")

        diff = call("POST", "/difficulty/next", token=p_token, body={
            "category": "memory",
            "currentDifficulty": "gentle",
            "correctCount": 3,
            "totalCount": 4,
            "hintCount": 0,
            "durationSec": 90,
        })
        check("adaptive difficulty returns a level",
              diff.get("difficulty") in ("gentle", "standard", "challenging"),
              f"difficulty={diff.get('difficulty')} source={diff.get('source')}")

        # ── Idempotent retransmission ────────────────────────────────────
        re_push = call("POST", "/sync/push", token=p_token, body={"records": activity_records})
        check("re-push is idempotent",
              re_push.get("accepted") == ["e2e-activity-0", "e2e-activity-1"])
        analytics2 = call("GET", f"/analytics/patient/{p_acct}", token=c_token)
        check("no duplicate analytics after re-push", analytics2.get("totalAttempts") == 2)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print()
    if FAILED:
        print(f"E2E FAILED: {len(FAILED)} step(s) -> {', '.join(FAILED)}")
        return 1
    print(f"E2E OK | all {STEP_COUNT[0]} steps passed (two-device flow verified over real HTTP)")
    return 0


if __name__ == "__main__":
    sys.exit(main())