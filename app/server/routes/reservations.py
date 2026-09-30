from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .. import queries as q
from ..db import get_pool
from ..serialize import jsonable

router = APIRouter()


def _rows(cur):
    cols = [d.name for d in cur.description]
    return [jsonable(dict(zip(cols, r))) for r in cur.fetchall()]


@router.get("/reservations")
def list_reservations(
    hotel: Optional[str] = None,
    risk_band: Optional[str] = None,
    market_segment: Optional[str] = None,
    min_lead_time: Optional[int] = None,
    limit: Optional[int] = Query(default=None),
    offset: Optional[int] = Query(default=None),
):
    try:
        where, params = q.build_reservation_filters(
            hotel=hotel, risk_band=risk_band,
            market_segment=market_segment, min_lead_time=min_lead_time,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    lim, off = q.clamp_limit(limit), q.clamp_offset(offset)
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(q.count_query(where), params)
            total = cur.fetchone()[0]
            cur.execute(q.reservations_query(where), params + [lim, off])
            items = _rows(cur)
    return {"total": total, "limit": lim, "offset": off, "items": items}


@router.get("/reservations/{reservation_id}")
def get_reservation(reservation_id: str):
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(q.detail_query(), [reservation_id])
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="reservation not found")
            cols = [d.name for d in cur.description]
            reservation = jsonable(dict(zip(cols, row)))
            cur.execute(q.prior_actions_query(), [reservation_id])
            actions = _rows(cur)
    return {"reservation": reservation, "actions": actions}
