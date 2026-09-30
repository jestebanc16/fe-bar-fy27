from fastapi import APIRouter

from .. import queries as q
from ..db import get_pool

router = APIRouter()


@router.get("/kpis")
def get_kpis():
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(q.kpi_query())
            total, high, med, low, avg = cur.fetchone()
    return {
        "total": total,
        "high_risk": high,
        "medium_risk": med,
        "low_risk": low,
        "avg_cancel_probability": float(avg) if avg is not None else None,
        "risk_band_mix": [
            {"risk_band": "high", "count": high},
            {"risk_band": "medium", "count": med},
            {"risk_band": "low", "count": low},
        ],
    }
