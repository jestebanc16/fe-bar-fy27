"""Row -> JSON-serializable dict conversion (pure, unit-tested)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal


def jsonable(row: dict) -> dict:
    out: dict = {}
    for key, value in row.items():
        if isinstance(value, (date, datetime)):
            out[key] = value.isoformat()
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out
