"""Runtime configuration for the Companio backend.

Two SQLite stores are used for the ML training story:

* ``MINDCARE_LIVE_DB``  - the live database the running server reads/writes.
* ``MINDCARE_TRAIN_DB`` - the demo/seed database used as a frozen training
  baseline. Retraining always fits on ``TRAIN_DB ∪ LIVE_DB`` so real-time
  usage keeps refining the model without losing the seeded knowledge.
"""

from __future__ import annotations

import os
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = SERVER_DIR / "data"
MODELS_DIR = SERVER_DIR / "models"

DATA_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def _abs(path: str | Path) -> Path:
    """Resolves relative paths against the server directory."""
    p = Path(path)
    return p if p.is_absolute() else SERVER_DIR / p


DATABASE_URL: str = os.getenv(
    "MINDCARE_LIVE_DB", f"sqlite:///{DATA_DIR / 'companio.db'}"
)
TRAIN_DATABASE_URL: str = os.getenv(
    "MINDCARE_TRAIN_DB", f"sqlite:///{DATA_DIR / 'demo.db'}"
)
MODEL_PATH: Path = _abs(os.getenv("MINDCARE_MODEL_PATH", str(MODELS_DIR / "difficulty_model.pkl")))

JWT_SECRET: str = os.getenv(
    "MINDCARE_JWT_SECRET", "companio-dev-secret-change-me-73e5a1f28c4b9d0e"
)
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = int(os.getenv("MINDCARE_JWT_EXPIRY_MINUTES", "43200"))  # 30 days

PAIRING_CODE_LENGTH: int = 6

# ML training gates --------------------------------------------------------
MIN_TRAINING_SAMPLES: int = 100
MIN_TRAINING_DOMAINS: int = 2
MIN_PATIENT_COVERAGE: int = 1
MIN_HOLDOUT_ACCURACY: float = 0.60
MIN_HOLDOUT_MARGIN: float = 0.05  # must beat majority-class baseline by this
HOLDOUT_FRACTION: float = 0.20
MIN_PATIENT_SAMPLES_FOR_PERSONALIZATION: int = 10
RANDOM_SEED: int = 42