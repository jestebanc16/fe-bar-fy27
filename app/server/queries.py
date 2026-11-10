"""Pure SQL builders + validators for the revenue-manager app.

No database, no environment, no I/O — every function here is deterministic and
unit-tested (see tests/test_queries.py). Routes (server/routes/*) compose these
with the connection pool in server/db.py.

SERVING_SCHEMA defaults to the dev UC/Postgres schema; override via the
SERVING_SCHEMA env var (set per target in app.yaml / deploy) so prod can point
at hotel_booking without code changes.
"""
from __future__ import annotations

import os

VALID_ACTION_TYPES: tuple[str, ...] = (
    "reconfirmed", "deposit_requested", "overbooked_backup", "released", "note",
)
VALID_RISK_BANDS: tuple[str, ...] = ("high", "medium", "low")

SERVING_SCHEMA = os.environ.get("SERVING_SCHEMA", "hotel_booking_dev")
SERVING_TABLE = f"{SERVING_SCHEMA}.reservation_risk_serving_synced"
ACTION_TABLE = "public.reservation_action"

RESERVATION_COLUMNS = (
    "reservation_id, hotel, arrival_date, lead_time, adr, market_segment, "
    "adults, children, babies, deposit_type, customer_type, "
    "cancel_probability, risk_band, model_version, scored_at"
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_limit(raw) -> int:
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, val))


def clamp_offset(raw) -> int:
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, val)


def validate_action_type(value) -> bool:
    return value in VALID_ACTION_TYPES


def build_reservation_filters(*, hotel=None, risk_band=None,
                              market_segment=None, min_lead_time=None):
    clauses: list[str] = []
    params: list = []
    if hotel:
        clauses.append("hotel = %s")
        params.append(hotel)
    if risk_band:
        if risk_band not in VALID_RISK_BANDS:
            raise ValueError(f"unknown risk_band: {risk_band}")
        clauses.append("risk_band = %s")
        params.append(risk_band)
    if market_segment:
        clauses.append("market_segment = %s")
        params.append(market_segment)
    if min_lead_time is not None:
        clauses.append("lead_time >= %s")
        params.append(min_lead_time)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def reservations_query(where_sql: str) -> str:
    return (
        f"SELECT {RESERVATION_COLUMNS} FROM {SERVING_TABLE}"
        f"{where_sql} ORDER BY cancel_probability DESC LIMIT %s OFFSET %s"
    )


def count_query(where_sql: str) -> str:
    return f"SELECT count(*) FROM {SERVING_TABLE}{where_sql}"


def detail_query() -> str:
    return f"SELECT {RESERVATION_COLUMNS} FROM {SERVING_TABLE} WHERE reservation_id = %s"


def prior_actions_query() -> str:
    return (
        "SELECT id, reservation_id, action_type, note, acted_by, acted_at "
        f"FROM {ACTION_TABLE} WHERE reservation_id = %s ORDER BY acted_at DESC"
    )


def insert_action_query() -> str:
    return (
        f"INSERT INTO {ACTION_TABLE} (reservation_id, action_type, note, acted_by) "
        "VALUES (%s, %s, %s, %s) "
        "RETURNING id, reservation_id, action_type, note, acted_by, acted_at"
    )


def kpi_query() -> str:
    return (
        "SELECT count(*) AS total, "
        "count(*) FILTER (WHERE risk_band='high') AS high_risk, "
        "count(*) FILTER (WHERE risk_band='medium') AS medium_risk, "
        "count(*) FILTER (WHERE risk_band='low') AS low_risk, "
        "avg(cancel_probability) AS avg_cancel_probability "
        f"FROM {SERVING_TABLE}"
    )
