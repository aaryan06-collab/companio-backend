"""Feature engineering for the adaptive-difficulty model.

Features are derived ONLY from real observations (ActivityRecord rows) plus
the immediate request context. The model is deliberately small and
explainable: one categorical domain + a compact numeric feature set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .. import models

DIFFICULTY_ORDER = ["gentle", "comfortable", "challenging"]


def difficulty_index(name: str) -> int:
    try:
        return DIFFICULTY_ORDER.index(name)
    except ValueError:
        return 0


FEATURE_COLUMNS = [
    "category",
    "current_difficulty",
    "accuracy",
    "hint_rate",
    "duration_minutes",
    "hour",
    "days_in_program",
    "domain_slope",
]


def accuracy(correct: int, total: int) -> float:
    return correct / total if total > 0 else 0.0


def _ordered(rows: Sequence[models.ActivityRecord]) -> list[models.ActivityRecord]:
    return sorted(rows, key=lambda r: (r.started_at, r.id))


def _trailing_slope(accs: list[float]) -> float:
    """Slope proxy: (mean of most recent 3) minus (mean of the rest before)."""
    if len(accs) < 4:
        return 0.0
    recent = accs[-3:]
    prev = accs[:-3]
    return (sum(recent) / len(recent)) - (sum(prev) / len(prev))


def patient_first_dates(rows: Sequence[models.ActivityRecord]) -> dict[str, datetime]:
    first: dict[str, datetime] = {}
    for row in _ordered(rows):
        if row.patient_account_id not in first:
            first[row.patient_account_id] = row.started_at
    return first


def row_features(row: models.ActivityRecord,
                 same_domain_history: Sequence[models.ActivityRecord],
                 patient_first: datetime) -> dict:
    """Features for one training row.

    ``same_domain_history`` must be that patient's rows in the same category,
    ordered by time and INCLUDING the current row (it is the last element).
    """
    prior = [accuracy(r.correct, r.total) for r in same_domain_history[:-1]]

    minutes = 0.0
    if row.finished_at and row.started_at:
        delta = (row.finished_at - row.started_at).total_seconds() / 60.0
        minutes = max(delta, 0.0)

    days_in_program = max((row.started_at - patient_first).days, 0)

    return {
        "category": row.category,
        "current_difficulty": difficulty_index(row.difficulty),
        "accuracy": accuracy(row.correct, row.total),
        "hint_rate": min(row.hints / max(row.total, 1), 1.0),
        "duration_minutes": minutes,
        "hour": row.started_at.hour,
        "days_in_program": days_in_program,
        "domain_slope": _trailing_slope(prior),
    }


def request_features(
    *,
    category: str,
    current_difficulty: str,
    correct: int,
    total: int,
    hints: int,
    duration_sec: int,
    domain_slope: float,
    days_in_program: int,
    hour: int,
) -> dict:
    return {
        "category": category,
        "current_difficulty": difficulty_index(current_difficulty),
        "accuracy": accuracy(correct, total),
        "hint_rate": min(hints / max(total, 1), 1.0),
        "duration_minutes": duration_sec / 60.0,
        "hour": hour,
        "days_in_program": days_in_program,
        "domain_slope": domain_slope,
    }


def group_history(rows: Sequence[models.ActivityRecord]) -> dict[tuple[str, str], list[models.ActivityRecord]]:  # noqa: E501
    """Rows grouped by (patient, category), each ordered by time."""
    groups: dict[tuple[str, str], list[models.ActivityRecord]] = {}
    for row in rows:
        key = (row.patient_account_id, row.category)
        groups.setdefault(key, []).append(row)
    return {key: _ordered(v) for key, v in groups.items()}