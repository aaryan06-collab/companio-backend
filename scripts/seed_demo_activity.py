"""Seeds the demo (training) SQLite database with realistic activity sessions.

The records are stamped ``source: demo`` and represent the frozen training
baseline. Training later fits on ``demo.db ∪ live.db`` so a model always
exists for the SIH demo while real-time usage keeps refining it.

Usage:
    python scripts/seed_demo_activity.py [--db path] [--patients 6] [--samples 1200] [--days 30]

Run from the ``server/`` directory so ``app`` is importable.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, models  # noqa: E402
from app.database import make_session  # noqa: E402
from app.models import new_id  # noqa: E402

CATEGORIES = [
    "memory",
    "everyday",
    "numeracy",
    "festivals",
    "food",
    "region",
    "attention",
]
DIFFICULTIES = ["gentle", "comfortable", "challenging"]

# Per-difficulty accuracy shift around a patient's base ability.
DIFFICULTY_SHIFT = {"gentle": 0.08, "comfortable": 0.0, "challenging": -0.10}


def _clamp(v: float, lo: float = 0.12, hi: float = 0.98) -> float:
    return max(lo, min(hi, v))


def build_sessions(rng: random.Random, base_date: datetime) -> list[models.ActivityRecord]:
    records: list[models.ActivityRecord] = []
    for patient_idx in range(1, 7):
        patient_id = f"demo-patient-{patient_idx}"
        ability = rng.uniform(0.45, 0.92)  # mixed cognitive baselines
        for day in range(30):
            for _ in range(rng.randint(1, 3)):
                category = rng.choice(CATEGORIES)
                difficulty = rng.choices(
                    DIFFICULTIES, weights=[0.5, 0.35, 0.15], k=1
                )[0]
                total = rng.randint(3, 8)
                hints = rng.choices([0, 1, 2, 3], weights=[0.4, 0.3, 0.2, 0.1], k=1)[0]
                target_acc = _clamp(ability + DIFFICULTY_SHIFT[difficulty] + rng.uniform(-0.12, 0.12))
                correct = min(total, max(0, round(total * target_acc)))
                if rng.random() < 0.15 and correct == total:
                    correct -= 1  # some sessions are imperfect
                completed = rng.random() < 0.9

                minutes = rng.uniform(0.5, 12.0)
                started = base_date + timedelta(days=day, hours=rng.randint(5, 21), minutes=rng.randint(0, 59))
                finished = started + timedelta(minutes=minutes)

                records.append(
                    models.ActivityRecord(
                        id=new_id("act"),
                        patient_account_id=patient_id,
                        device_id=f"demo-device-{patient_idx}",
                        activity_id=f"demo-activity-{rng.randint(1, 14)}",
                        category=category,
                        difficulty=difficulty,
                        started_at=started,
                        finished_at=finished,
                        completed=completed,
                        correct=correct,
                        total=total,
                        hints=hints,
                        source="demo",
                    )
                )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the demo training database")
    parser.add_argument("--db", default=config.TRAIN_DATABASE_URL, help="Demo SQLite DSN")
    parser.add_argument("--patients", type=int, default=6)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--samples", type=int, default=1200, help="Approximate target record count")
    args = parser.parse_args()

    db_url: str = args.db
    session = make_session(db_url)

    rng = random.Random(config.RANDOM_SEED)
    base_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=args.days)

    for patient_idx in range(1, args.patients + 1):
        ability = rng.uniform(0.45, 0.92)
        for day in range(args.days):
            daily = max(1, args.samples // (args.patients * args.days))
            for _ in range(daily):
                category = rng.choice(CATEGORIES)
                difficulty = rng.choices(DIFFICULTIES, weights=[0.5, 0.35, 0.15], k=1)[0]
                total = rng.randint(3, 8)
                hints = rng.choices([0, 1, 2, 3], weights=[0.4, 0.3, 0.2, 0.1], k=1)[0]
                target_acc = _clamp(ability + DIFFICULTY_SHIFT[difficulty] + rng.uniform(-0.12, 0.12))
                correct = min(total, max(0, round(total * target_acc)))
                if rng.random() < 0.15 and correct == total:
                    correct -= 1
                completed = rng.random() < 0.9
                minutes = rng.uniform(0.5, 12.0)
                started = base_date + timedelta(days=day, hours=rng.randint(5, 21), minutes=rng.randint(0, 59))
                finished = started + timedelta(minutes=minutes)
                session.add(
                    models.ActivityRecord(
                        id=new_id("act"),
                        patient_account_id=f"demo-patient-{patient_idx}",
                        device_id=f"demo-device-{patient_idx}",
                        activity_id=f"demo-activity-{rng.randint(1, 14)}",
                        category=category,
                        difficulty=difficulty,
                        started_at=started,
                        finished_at=finished,
                        completed=completed,
                        correct=correct,
                        total=total,
                        hints=hints,
                        source="demo",
                    )
                )
    session.commit()
    total = (
        session.query(models.ActivityRecord).count()
    )
    print(f"Seeded {total} demo activity records into {db_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())