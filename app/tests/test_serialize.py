from datetime import date, datetime
from decimal import Decimal

from server.serialize import jsonable


def test_jsonable_converts_dates_and_decimals():
    row = {
        "reservation_id": "abc",
        "arrival_date": date(2016, 7, 1),
        "scored_at": datetime(2026, 9, 29, 20, 55, 42),
        "adr": Decimal("123.45"),
        "lead_time": 30,
        "note": None,
    }
    out = jsonable(row)
    assert out["arrival_date"] == "2016-07-01"
    assert out["scored_at"].startswith("2026-09-29T20:55:42")
    assert out["adr"] == 123.45 and isinstance(out["adr"], float)
    assert out["lead_time"] == 30
    assert out["note"] is None
    assert out["reservation_id"] == "abc"
