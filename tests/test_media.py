"""Media upload + serve round trip for caregiver photo/video/voice memories."""

from __future__ import annotations

from conftest import _auth

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 512
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 512
M4A_BYTES = b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 512


def test_upload_and_fetch_round_trip(client, caregiver_ctx):
    r = client.post(
        "/media/upload",
        headers=_auth(caregiver_ctx["token"]),
        files={"file": ("family.png", PNG_BYTES, "image/png")},
        data={"deviceId": caregiver_ctx["deviceId"]},
    )
    assert r.status_code == 200, r.text
    url = r.json()["url"]

    fetched = client.get(url, headers=_auth(caregiver_ctx["token"]))
    assert fetched.status_code == 200
    assert fetched.content.startswith(b"\x89PNG")


def test_video_and_audio_upload(client, caregiver_ctx):
    for name, payload, mime in (
        ("clip.mp4", MP4_BYTES, "video/mp4"),
        ("voice.m4a", M4A_BYTES, "audio/mp4"),
    ):
        r = client.post(
            "/media/upload",
            headers=_auth(caregiver_ctx["token"]),
            files={"file": (name, payload, mime)},
            data={"deviceId": caregiver_ctx["deviceId"]},
        )
        assert r.status_code == 200, r.text
        url = r.json()["url"]

        fetched = client.get(url, headers=_auth(caregiver_ctx["token"]))
        assert fetched.status_code == 200
        assert fetched.content == payload


def test_media_requires_auth(client, caregiver_ctx):
    r = client.post(
        "/media/upload",
        headers=_auth(caregiver_ctx["token"]),
        files={"file": ("family.png", PNG_BYTES, "image/png")},
        data={"deviceId": caregiver_ctx["deviceId"]},
    )
    url = r.json()["url"]

    assert client.get(url).status_code == 401

    first = client.post(
        "/media/upload",
        files={"file": ("family.png", PNG_BYTES, "image/png")},
        data={"deviceId": caregiver_ctx["deviceId"]},
    )
    assert first.status_code in (401, 403)


def test_non_media_rejected(client, caregiver_ctx):
    for name, payload, mime in (
        ("note.txt", b"hello", "text/plain"),
        ("script.py", b"print(1)", "text/x-python"),
    ):
        r = client.post(
            "/media/upload",
            headers=_auth(caregiver_ctx["token"]),
            files={"file": (name, payload, mime)},
            data={"deviceId": caregiver_ctx["deviceId"]},
        )
        assert r.status_code == 415, name


def test_patient_can_fetch_their_photo(client, patient_ctx, caregiver_ctx):
    r = client.post(
        "/media/upload",
        headers=_auth(caregiver_ctx["token"]),
        files={"file": ("pic.png", PNG_BYTES, "image/png")},
        data={"deviceId": caregiver_ctx["deviceId"]},
    )
    assert r.status_code == 200, r.text
    url = r.json()["url"]

    fetched = client.get(url, headers=_auth(patient_ctx["token"]))
    assert fetched.status_code == 200
    assert fetched.content.startswith(b"\x89PNG")


def test_traversal_names_are_not_found(client, caregiver_ctx):
    for bad in ("..%2F..%2Fcompanio.db", "../../companio.db", "x.py"):
        r = client.get(
            f"/media/{bad}",
            headers=_auth(caregiver_ctx["token"]),
        )
        assert r.status_code == 404, f"{bad} -> {r.status_code}"