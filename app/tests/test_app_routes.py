def test_api_routes_registered():
    from app import app  # importing app.py does no network I/O (lazy pool)
    # Starlette 1.7 includes routers lazily (app.routes holds _IncludedRouter
    # placeholders), so inspect the OpenAPI schema — a stable public API that
    # reflects every registered path without triggering the lifespan/DB.
    paths = set(app.openapi()["paths"].keys())
    assert "/api/health" in paths
    assert "/api/kpis" in paths
    assert "/api/reservations" in paths
    assert "/api/reservations/{reservation_id}" in paths
    assert "/api/reservations/{reservation_id}/actions" in paths
