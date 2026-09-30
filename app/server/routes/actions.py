from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import queries as q
from ..config import resolve_acted_by
from ..db import get_pool
from ..serialize import jsonable

router = APIRouter()


class ActionIn(BaseModel):
    action_type: str
    note: Optional[str] = None


@router.post("/reservations/{reservation_id}/actions")
def create_action(reservation_id: str, body: ActionIn, request: Request):
    if not q.validate_action_type(body.action_type):
        raise HTTPException(status_code=400, detail=f"invalid action_type: {body.action_type}")
    acted_by = resolve_acted_by(request.headers)
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                q.insert_action_query(),
                [reservation_id, body.action_type, body.note, acted_by],
            )
            row = cur.fetchone()
            cols = [d.name for d in cur.description]
        conn.commit()
    return jsonable(dict(zip(cols, row)))
