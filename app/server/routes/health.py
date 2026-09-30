from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..db import get_pool

router = APIRouter()


@router.get("/health")
def health():
    try:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001 — surface DB unreachability as 503
        return JSONResponse(status_code=503, content={"status": "unavailable", "detail": str(exc)})
