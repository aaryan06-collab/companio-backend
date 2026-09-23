"""Companio backend - FastAPI application entrypoint.

Run locally:
    uvicorn app.main:app --host 0.0.0.0 --port 8000

Bind to 0.0.0.0 so both Android phones can reach the laptop over LAN.
"""

from __future__ import annotations

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .routers import admin, analytics, auth, difficulty, media, sos, sync

app = FastAPI(
    title="Companio API",
    version="1.0.0",
    description="AI-based cognitive gaming and memory assistance platform for "
    "elderly dementia patients in the North Eastern Region (SIH #26003).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(sos.router)
app.include_router(analytics.router)
app.include_router(difficulty.router)
app.include_router(admin.router)
app.include_router(media.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Placeholder landing page for the HF Space."""
    return """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Companio API</title>
    <style>body{font-family:system-ui,sans-serif;max-width:640px;margin:48px auto;
    padding:0 16px;color:#1f2937;background:#f8fafc}
    h1{font-size:1.7rem}a{color:#2563eb;text-decoration:none}</style>
</head>
<body>
    <h1>Companio API</h1>
    <p>Placeholder landing page — comes to life shortly.</p>
    <ul>
        <li><a href="/docs">Interactive API docs</a></li>
        <li><a href="/health">Health check</a></li>
        <li><a href="/admin/model-card">ML model card</a></li>
    </ul>
</body>
</html>"""


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "unreachable",
        "service": "companio",
        "version": app.version,
    }