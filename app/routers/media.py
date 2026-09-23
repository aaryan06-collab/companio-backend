"""Media endpoints: upload + serve caregiver photo memories.

Photos are written to disk under ``MEDIA_DIR`` and scoped to the calling
device's patient (mirroring the sync inbox). Files are served to any
authenticated family member so a pulled memory's ``mediaUrl`` renders on a
separate device. JWT may come via the ``Authorization`` header (used by the
app's ``Image.network(headers: ...)``) or the ``?token=`` query parameter.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .. import config, models
from ..database import get_db
from ..deps import current_account, device_for
from ..schemas import MediaUploadResponse
from ..security import decode_token

router = APIRouter(prefix="/media", tags=["media"])

MAX_MEDIA_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "heic", "heif"}
SAFE_NAME = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{2,5}$")

_bearer = HTTPBearer(auto_error=False)


def _resolve_patient(db: Session, device_id: str, account: models.Account) -> str:
    dev = device_for(db, device_id) if device_id else None
    if dev is not None and dev.patient_id:
        return dev.patient_id
    if account.role == "patient":
        return account.id
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "Device is not mapped to a patient (patient or linked caregiver)",
    )


def _require_auth(
    creds: HTTPAuthorizationCredentials | None,
    token: str | None,
) -> dict:
    raw = token or (creds.credentials if creds is not None else None)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing credentials")
    try:
        return decode_token(raw)
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc


@router.post("/upload", response_model=MediaUploadResponse)
async def upload_media(
    file: UploadFile,
    deviceId: str = Form(default=""),
    account: models.Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS or file.content_type is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Only image uploads are allowed (jpg, png, webp, gif, heic)",
        )

    data = await file.read()
    if len(data) > MAX_MEDIA_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "Image exceeds 10 MB",
        )

    patient_id = _resolve_patient(db, deviceId, account)
    name = f"{uuid.uuid4().hex}.{ext}"
    (config.MEDIA_DIR / name).write_bytes(data)

    db.add(
        models.MediaAsset(
            id=name,
            patient_id=patient_id,
            account_id=account.id,
            size_bytes=len(data),
        )
    )
    db.commit()

    return MediaUploadResponse(url=f"/media/{name}")


@router.get("/{name}")
def get_media(
    name: str,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(default=None),
):
    _require_auth(creds, token)
    if not SAFE_NAME.match(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    path = config.MEDIA_DIR / name
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(path)