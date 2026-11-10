"""FastAPI entry point: lifespan-managed Lakebase pool, /api routes, SPA mount."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.db import close_pool, open_pool
from server.routes import actions, health, kpis, reservations


@asynccontextmanager
async def lifespan(_app: FastAPI):
    open_pool()          # fail fast if the DB is unreachable
    yield
    close_pool()


app = FastAPI(title="Meridian Hotels & Resorts – Revenue-Manager App", lifespan=lifespan)

for module in (health, kpis, reservations, actions):
    app.include_router(module.router, prefix="/api")

# Serve the built React SPA when present (populated by `npm run build`, Task 6).
_frontend = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(_frontend):
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):  # noqa: ARG001 — SPA catch-all
        return FileResponse(os.path.join(_frontend, "index.html"))
