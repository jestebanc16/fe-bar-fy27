# Hotel Revenue-Manager Databricks App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a modern, responsive FastAPI + React revenue-manager app that reads at-risk reservations from Lakebase, shows portfolio KPIs, and writes operational actions back to Postgres — deployed as a DABs `apps` resource.

**Architecture:** A FastAPI backend (uv) serves a built React/TypeScript SPA and exposes a small `/api` over a single Lakebase Postgres connection pool (DB `hotel`, instance `hotel-lakebase`). Pure SQL-builder + validator functions are unit-tested; DB/route behavior is verified manually. Connection auth uses the classic GA Database-Instance credential path (`w.database.generate_database_credential`) with runtime-injected `PGHOST`/`PGUSER` (Approach A) and an SDK `read_write_dns` fallback (Approach B). The app is declared in `resources/hotel_app.yml` and shipped by `databricks bundle deploy`.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, `psycopg[binary,pool]`, `databricks-sdk` (`w.database`, ≥0.143.0); React 18 + TypeScript + Vite, Tailwind CSS (class dark mode), `lucide-react`, `react-hot-toast`, minimal Zustand; DABs `apps` resource; pytest for unit tests.

## Global Constraints

- **Workspace / DB:** `fevm-fe-bar-ecastillo` · Lakebase instance `hotel-lakebase` (CU_1, GA/Provisioned tier) · logical Postgres DB `hotel`.
- **Read table (Postgres):** `hotel_booking_dev.reservation_risk_serving_synced` — the UC schema name carries over into Postgres. Columns: `reservation_id (text, PK), hotel (text), arrival_date (date), lead_time (int), adr (double), market_segment (text), adults (int), children (int), babies (int), deposit_type (text), customer_type (text), cancel_probability (double), risk_band (text: high|medium|low), model_version, scored_at (timestamp)`.
- **Write table (Postgres):** `public.reservation_action` — `id BIGSERIAL PK, reservation_id TEXT NOT NULL, action_type TEXT CHECK IN ('reconfirmed','deposit_requested','overbooked_backup','released','note'), note TEXT, acted_by TEXT, acted_at TIMESTAMPTZ DEFAULT now()`. Index `ix_reservation_action_res (reservation_id, acted_at DESC)` exists.
- **Connection auth is the classic GA path** — `w.database.generate_database_credential(request_id=str(uuid4()), instance_names=["hotel-lakebase"]).token` and host `w.database.get_database_instance("hotel-lakebase").read_write_dns`. **Do NOT** use the Autoscaling `w.postgres.generate_database_credential(endpoint=...)` / `ENDPOINT_NAME` pattern from the databricks-apps skill.
- **Single data plane:** all app data (reads, KPIs, writes) comes from Lakebase Postgres. No SQL warehouse, no gold/Delta path.
- **Deploy via bundle:** the app is a `resources/hotel_app.yml` `apps` resource; `databricks bundle deploy -t dev` ships it. CLI/deploy/grant/verify steps run **outside the sandbox** (`required_permissions=["all"]`), same as prior slices.
- **Instance must be running:** `hotel-lakebase` is set `stopped: true` when idle; start it before deploy/verify.
- **`acted_by`:** in-app from forwarded identity header `X-Forwarded-Email` (fallback `X-Forwarded-Preferred-Username`); locally the CLI user email; final fallback `"local-dev"`. No on-behalf-of DB auth.
- **YAGNI:** no AI/Genie/serving-endpoint scoring, no action edit/delete, no auto-refresh.
- **Commit after each task.** Commits/writes run with `required_permissions=["all"]` (repo pre-commit hooks run). Push uses the `jestebanc16` remote with `required_permissions=["full_network","git_write"]` + smart-mode approval, per repo convention.
- **`SERVING_TABLE`** is `hotel_booking_dev.reservation_risk_serving_synced` for the dev target (prod would be `hotel_booking...`); it is a single module constant with a documented prod-override note.

---

### Task 1: Backend scaffold + pure query/validator layer (TDD)

**Files:**
- Create: `app/pyproject.toml`
- Create: `app/.gitignore`
- Create: `app/server/__init__.py` (empty)
- Create: `app/server/queries.py`
- Create: `app/tests/__init__.py` (empty)
- Test: `app/tests/test_queries.py`

**Interfaces:**
- Produces (all pure, no DB, no env):
  - Constants `VALID_ACTION_TYPES: tuple[str,...]`, `VALID_RISK_BANDS: tuple[str,...]`, `SERVING_TABLE: str`, `ACTION_TABLE: str`, `RESERVATION_COLUMNS: str`, `DEFAULT_LIMIT=50`, `MAX_LIMIT=200`.
  - `clamp_limit(raw) -> int` (1..200, default 50), `clamp_offset(raw) -> int` (>=0, default 0).
  - `validate_action_type(value) -> bool`.
  - `build_reservation_filters(*, hotel=None, risk_band=None, market_segment=None, min_lead_time=None) -> tuple[str, list]` — returns `(" WHERE ...", params)` or `("", [])`; raises `ValueError` on an unknown `risk_band`.
  - `reservations_query(where_sql: str) -> str`, `count_query(where_sql: str) -> str`, `detail_query() -> str`, `prior_actions_query() -> str`, `insert_action_query() -> str`, `kpi_query() -> str`.
- Consumed by Task 3 (routes) and Task 2 (none).

- [ ] **Step 1: Write the failing tests**

Create `app/tests/__init__.py` (empty) and `app/tests/test_queries.py`:

```python
import pytest
from server import queries as q


def test_action_type_validation():
    assert q.validate_action_type("reconfirmed") is True
    assert q.validate_action_type("released") is True
    assert q.validate_action_type("bogus") is False
    assert set(q.VALID_ACTION_TYPES) == {
        "reconfirmed", "deposit_requested", "overbooked_backup", "released", "note",
    }


def test_clamp_limit_bounds():
    assert q.clamp_limit(None) == q.DEFAULT_LIMIT
    assert q.clamp_limit("10") == 10
    assert q.clamp_limit(0) == 1
    assert q.clamp_limit(9999) == q.MAX_LIMIT
    assert q.clamp_limit("junk") == q.DEFAULT_LIMIT


def test_clamp_offset_bounds():
    assert q.clamp_offset(None) == 0
    assert q.clamp_offset("40") == 40
    assert q.clamp_offset(-5) == 0
    assert q.clamp_offset("junk") == 0


def test_build_filters_empty():
    where, params = q.build_reservation_filters()
    assert where == ""
    assert params == []


def test_build_filters_all():
    where, params = q.build_reservation_filters(
        hotel="City Hotel", risk_band="high", market_segment="Online TA", min_lead_time=30,
    )
    assert where.startswith(" WHERE ")
    assert where.count("%s") == 4
    assert "hotel = %s" in where
    assert "risk_band = %s" in where
    assert "market_segment = %s" in where
    assert "lead_time >= %s" in where
    assert params == ["City Hotel", "high", "Online TA", 30]


def test_build_filters_rejects_bad_risk_band():
    with pytest.raises(ValueError):
        q.build_reservation_filters(risk_band="extreme")


def test_reservations_query_orders_and_pages():
    sql = q.reservations_query(" WHERE hotel = %s")
    assert q.SERVING_TABLE in sql
    assert "ORDER BY cancel_probability DESC" in sql
    assert "LIMIT %s OFFSET %s" in sql
    assert "WHERE hotel = %s" in sql


def test_count_query_uses_same_where():
    sql = q.count_query(" WHERE risk_band = %s")
    assert sql.strip().lower().startswith("select count(*)")
    assert q.SERVING_TABLE in sql
    assert "WHERE risk_band = %s" in sql


def test_detail_and_actions_queries():
    assert "WHERE reservation_id = %s" in q.detail_query()
    assert q.SERVING_TABLE in q.detail_query()
    pa = q.prior_actions_query()
    assert q.ACTION_TABLE in pa
    assert "ORDER BY acted_at DESC" in pa
    assert "WHERE reservation_id = %s" in pa


def test_insert_action_query_shape():
    ins = q.insert_action_query()
    assert q.ACTION_TABLE in ins
    assert "(reservation_id, action_type, note, acted_by)" in ins
    assert "VALUES (%s, %s, %s, %s)" in ins
    assert "RETURNING id, reservation_id, action_type, note, acted_by, acted_at" in ins


def test_kpi_query_has_filtered_counts():
    sql = q.kpi_query()
    assert "count(*)" in sql.lower()
    assert "filter (where risk_band='high')" in sql.lower()
    assert "avg(cancel_probability)" in sql.lower()
    assert q.SERVING_TABLE in sql
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app && uv run pytest tests/test_queries.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'server'` / `queries` (nothing implemented yet).

- [ ] **Step 3: Write `app/pyproject.toml` and `app/.gitignore`**

Create `app/pyproject.toml`:

```toml
[project]
name = "hotel-revenue-app"
version = "0.1.0"
description = "Revenue-manager app: at-risk reservations + write-back actions over Lakebase."
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.111",
    "uvicorn>=0.30",
    "psycopg[binary,pool]>=3.2",
    "databricks-sdk>=0.143.0",
    "pydantic>=2.7",
]

[dependency-groups]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]

[tool.uv]
package = false
```

Create `app/.gitignore`:

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
venv/
.env

# Node
node_modules/
npm-debug.log*

# Build outputs — KEEP frontend/dist (needed for deploy); do NOT ignore it.

# Databricks / IDE / OS
.databricks/
.idea/
*.swp
.DS_Store
```

- [ ] **Step 4: Implement `app/server/queries.py`**

Create `app/server/__init__.py` (empty) and `app/server/queries.py`:

```python
"""Pure SQL builders + validators for the revenue-manager app.

No database, no environment, no I/O — every function here is deterministic and
unit-tested (see tests/test_queries.py). Routes (server/routes/*) compose these
with the connection pool in server/db.py.
"""
from __future__ import annotations

VALID_ACTION_TYPES: tuple[str, ...] = (
    "reconfirmed", "deposit_requested", "overbooked_backup", "released", "note",
)
VALID_RISK_BANDS: tuple[str, ...] = ("high", "medium", "low")

# Dev target. For prod, override to hotel_booking.reservation_risk_serving_synced.
SERVING_TABLE = "hotel_booking_dev.reservation_risk_serving_synced"
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app && uv run pytest tests/test_queries.py -q`
Expected: PASS (all tests green).

- [ ] **Step 6: Commit**

```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27
git add app/pyproject.toml app/.gitignore app/server/__init__.py app/server/queries.py app/tests/__init__.py app/tests/test_queries.py
git commit -m "feat(app): backend scaffold + tested pure query/validator layer"
```

---

### Task 2: Dual-mode config + Lakebase connection (GA path, A+B fallback)

**Files:**
- Create: `app/server/config.py`
- Create: `app/server/db.py`
- Test: `app/tests/test_config.py`

**Interfaces:**
- `config.py` produces: `IS_DATABRICKS_APP: bool`; `get_workspace_client() -> WorkspaceClient`; `pick_acted_by(headers: Mapping[str,str], *, is_app: bool, cli_user: str|None) -> str` (pure, tested); `resolve_acted_by(headers: Mapping[str,str]) -> str` (wraps `pick_acted_by`, used by routes).
- `db.py` produces: `resolve_conn_params(env: Mapping[str,str], *, dns_lookup: Callable[[str],str], user_lookup: Callable[[],str]) -> dict` (pure, tested — keys `host,user,port,dbname,sslmode,instance`); `pool: ConnectionPool` (module-level, `open=False`); `open_pool()` / `close_pool()` used by the app lifespan (Task 3).
- Consumes: none from other tasks.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_config.py`:

```python
from server.config import pick_acted_by
from server.db import resolve_conn_params


def test_pick_acted_by_prefers_forwarded_email():
    hdrs = {"X-Forwarded-Email": "rev@corp.com"}
    assert pick_acted_by(hdrs, is_app=True, cli_user="ignored") == "rev@corp.com"


def test_pick_acted_by_falls_back_to_preferred_username():
    hdrs = {"X-Forwarded-Preferred-Username": "rev.manager"}
    assert pick_acted_by(hdrs, is_app=True, cli_user=None) == "rev.manager"


def test_pick_acted_by_local_uses_cli_user():
    assert pick_acted_by({}, is_app=False, cli_user="me@corp.com") == "me@corp.com"


def test_pick_acted_by_final_fallback():
    assert pick_acted_by({}, is_app=False, cli_user=None) == "local-dev"
    assert pick_acted_by({}, is_app=True, cli_user=None) == "local-dev"


def test_resolve_conn_params_uses_injected_pghost():
    env = {"PGHOST": "injected-host", "PGUSER": "sp-id", "PGDATABASE": "hotel",
           "DATABRICKS_INSTANCE_NAME": "hotel-lakebase"}
    params = resolve_conn_params(
        env, dns_lookup=lambda n: "should-not-be-called", user_lookup=lambda: "cli-user",
    )
    assert params["host"] == "injected-host"
    assert params["user"] == "sp-id"
    assert params["dbname"] == "hotel"
    assert params["sslmode"] == "require"
    assert params["instance"] == "hotel-lakebase"


def test_resolve_conn_params_falls_back_to_dns_and_cli_user():
    env = {"DATABRICKS_INSTANCE_NAME": "hotel-lakebase"}  # no PGHOST/PGUSER (local)
    params = resolve_conn_params(
        env, dns_lookup=lambda n: f"dns-of-{n}", user_lookup=lambda: "me@corp.com",
    )
    assert params["host"] == "dns-of-hotel-lakebase"
    assert params["user"] == "me@corp.com"
    assert params["dbname"] == "hotel"    # default
    assert params["port"] == "5432"       # default
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app && uv run pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError` for `server.config` / `server.db`.

- [ ] **Step 3: Implement `app/server/config.py`**

```python
"""Dual-mode auth + identity helpers.

Detects Databricks Apps (service-principal creds) vs local (CLI profile), and
derives `acted_by` for write-back attribution from the forwarded end-user
identity headers. No on-behalf-of DB auth — the app SP owns the connection.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

from databricks.sdk import WorkspaceClient

IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))


def get_workspace_client() -> WorkspaceClient:
    if IS_DATABRICKS_APP:
        return WorkspaceClient()  # auto-injected service-principal creds
    return WorkspaceClient(profile=os.environ.get("DATABRICKS_PROFILE", "DEFAULT"))


def pick_acted_by(headers: Mapping[str, str], *, is_app: bool,
                  cli_user: Optional[str]) -> str:
    """Pure identity resolution (unit-tested).

    Priority: forwarded email -> forwarded preferred-username -> CLI user
    (local only) -> "local-dev".
    """
    email = headers.get("X-Forwarded-Email") or headers.get("X-Forwarded-Preferred-Username")
    if email:
        return email
    if not is_app and cli_user:
        return cli_user
    return "local-dev"


def _cli_user() -> Optional[str]:
    try:
        return get_workspace_client().current_user.me().user_name
    except Exception:
        return None


def resolve_acted_by(headers: Mapping[str, str]) -> str:
    cli_user = None if IS_DATABRICKS_APP else _cli_user()
    return pick_acted_by(headers, is_app=IS_DATABRICKS_APP, cli_user=cli_user)
```

- [ ] **Step 4: Implement `app/server/db.py`**

```python
"""Lakebase Postgres connection pool — classic GA Database Instance path.

Credentials come from w.database.generate_database_credential(instance_names=...)
(NOT the Autoscaling w.postgres/ENDPOINT_NAME pattern). Host/user use the
runtime-injected PGHOST/PGUSER when present (Approach A) and fall back to the
SDK read_write_dns + CLI user (Approach B). A fresh OAuth token is minted per
connection; max_lifetime recycles connections before the 1-hour token expiry.

IMPORTANT: importing this module does NO network I/O. The workspace client and
the pool are created lazily in open_pool() (called from the app lifespan), so
unit tests can import resolve_conn_params without credentials.
"""
from __future__ import annotations

import os
import uuid
from typing import Callable, Mapping, Optional

import psycopg
from psycopg_pool import ConnectionPool

from .config import get_workspace_client

INSTANCE_NAME = os.environ.get("DATABRICKS_INSTANCE_NAME", "hotel-lakebase")

_w = None            # lazy WorkspaceClient
pool: Optional[ConnectionPool] = None


def _client():
    global _w
    if _w is None:
        _w = get_workspace_client()
    return _w


def resolve_conn_params(env: Mapping[str, str], *,
                        dns_lookup: Callable[[str], str],
                        user_lookup: Callable[[], str]) -> dict:
    instance = env.get("DATABRICKS_INSTANCE_NAME", "hotel-lakebase")
    host = env.get("PGHOST") or dns_lookup(instance)      # A -> B fallback
    user = env.get("PGUSER") or user_lookup()             # injected SP id, else CLI user
    return {
        "host": host,
        "user": user,
        "port": env.get("PGPORT", "5432"),
        "dbname": env.get("PGDATABASE", "hotel"),
        "sslmode": env.get("PGSSLMODE", "require"),
        "instance": instance,
    }


def _dns_lookup(instance: str) -> str:
    return _client().database.get_database_instance(name=instance).read_write_dns


def _user_lookup() -> str:
    return _client().current_user.me().user_name


class OAuthConnection(psycopg.Connection):
    """Mint a fresh Lakebase OAuth token for every new/recycled connection."""

    @classmethod
    def connect(cls, conninfo="", **kwargs):
        cred = _client().database.generate_database_credential(
            request_id=str(uuid.uuid4()), instance_names=[INSTANCE_NAME],
        )
        kwargs["password"] = cred.token
        return super().connect(conninfo, **kwargs)


def open_pool() -> None:
    """Build + open the pool. Called once from the app lifespan (Task 3)."""
    global pool
    params = resolve_conn_params(
        os.environ, dns_lookup=_dns_lookup, user_lookup=_user_lookup,
    )
    pool = ConnectionPool(
        conninfo=(
            f"dbname={params['dbname']} user={params['user']} "
            f"host={params['host']} port={params['port']} sslmode={params['sslmode']}"
        ),
        connection_class=OAuthConnection,
        min_size=1,
        max_size=10,
        max_lifetime=2700,  # 45 min — recycle before the 1-hour token expiry
        open=False,
    )
    pool.open(wait=True, timeout=30.0)


def close_pool() -> None:
    if pool is not None:
        pool.close()


def get_pool() -> ConnectionPool:
    if pool is None:
        raise RuntimeError("connection pool is not open")
    return pool
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app && uv run pytest tests/test_config.py -q`
Expected: PASS. Importing `server.db` does no network I/O (the client and pool are lazy), so the pure helpers test cleanly; the live pool/SDK wiring is verified in Task 8.

- [ ] **Step 6: Commit**

```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27
git add app/server/config.py app/server/db.py app/tests/test_config.py
git commit -m "feat(app): dual-mode config + Lakebase GA-instance pool (A+B fallback)"
```

---

### Task 3: FastAPI app + `/api` routes + SPA mount

**Files:**
- Create: `app/server/serialize.py`
- Create: `app/server/routes/__init__.py` (empty)
- Create: `app/server/routes/health.py`
- Create: `app/server/routes/kpis.py`
- Create: `app/server/routes/reservations.py`
- Create: `app/server/routes/actions.py`
- Create: `app/app.py`
- Test: `app/tests/test_serialize.py`, `app/tests/test_app_routes.py`

**Interfaces:**
- Consumes: `server.queries` (Task 1), `server.db.get_pool` (Task 2), `server.config.resolve_acted_by` (Task 2).
- Produces the HTTP contract used by the frontend (Tasks 4–6):
  - `GET /api/health` -> `{"status":"ok"}` (200) or `{"status":"unavailable",...}` (503).
  - `GET /api/kpis` -> `{total, high_risk, medium_risk, low_risk, avg_cancel_probability, risk_band_mix:[{risk_band,count}]}`.
  - `GET /api/reservations?hotel=&risk_band=&market_segment=&min_lead_time=&limit=&offset=` -> `{total, limit, offset, items:[Reservation]}`.
  - `GET /api/reservations/{reservation_id}` -> `{reservation: Reservation, actions:[Action]}` (404 if missing).
  - `POST /api/reservations/{reservation_id}/actions` body `{action_type, note?}` -> `Action` (400 on invalid `action_type`).
  - `serialize.jsonable(row: dict) -> dict` (pure, tested): dates/datetimes -> ISO strings, Decimals -> float.

- [ ] **Step 1: Write the failing tests**

Create `app/tests/test_serialize.py`:

```python
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
```

Create `app/tests/test_app_routes.py`:

```python
def test_api_routes_registered():
    from app import app  # importing app.py does no network I/O (lazy pool)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/health" in paths
    assert "/api/kpis" in paths
    assert "/api/reservations" in paths
    assert "/api/reservations/{reservation_id}" in paths
    assert "/api/reservations/{reservation_id}/actions" in paths
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app && uv run pytest tests/test_serialize.py tests/test_app_routes.py -q`
Expected: FAIL — `ModuleNotFoundError` for `server.serialize` / `app`.

- [ ] **Step 3: Implement `app/server/serialize.py`**

```python
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
```

- [ ] **Step 4: Implement the routes**

Create `app/server/routes/__init__.py` (empty).

Create `app/server/routes/health.py`:

```python
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
```

Create `app/server/routes/kpis.py`:

```python
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
```

Create `app/server/routes/reservations.py`:

```python
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
```

Create `app/server/routes/actions.py`:

```python
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
```

- [ ] **Step 5: Implement `app/app.py`**

```python
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


app = FastAPI(title="Hotel Revenue-Manager App", lifespan=lifespan)

for module in (health, kpis, reservations, actions):
    app.include_router(module.router, prefix="/api")

# Serve the built React SPA when present (populated by `npm run build`, Task 6).
_frontend = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(_frontend):
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):  # noqa: ARG001 — SPA catch-all
        return FileResponse(os.path.join(_frontend, "index.html"))
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app && uv run pytest -q`
Expected: PASS — all of `test_queries.py`, `test_config.py`, `test_serialize.py`, `test_app_routes.py` green (no DB/network required).

- [ ] **Step 7: Commit**

```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27
git add app/server/serialize.py app/server/routes app/app.py app/tests/test_serialize.py app/tests/test_app_routes.py
git commit -m "feat(app): FastAPI /api routes (kpis, reservations, actions, health) + SPA mount"
```

---

### Task 4: Frontend scaffold — Vite + TS + Tailwind (dark mode) + API client + shell

**Files:**
- Create: `app/frontend/package.json`, `app/frontend/tsconfig.json`, `app/frontend/tsconfig.node.json`
- Create: `app/frontend/vite.config.ts`, `app/frontend/tailwind.config.js`, `app/frontend/postcss.config.js`
- Create: `app/frontend/index.html`
- Create: `app/frontend/src/main.tsx`, `app/frontend/src/index.css`, `app/frontend/src/vite-env.d.ts`
- Create: `app/frontend/src/types.ts`, `app/frontend/src/api.ts`, `app/frontend/src/store.ts`
- Create: `app/frontend/src/App.tsx`
- Create: `app/frontend/src/components/Header.tsx`

**Interfaces:**
- Produces the TypeScript API contract mirroring Task 3, plus a Zustand UI store (`theme`, `selectedId`) and an `api` client. Consumed by Tasks 5–6.
- Dev proxy: Vite serves `:5173` and proxies `/api` -> `http://localhost:8000`. Prod build outputs to `frontend/dist` (served by FastAPI).

- [ ] **Step 1: Write `package.json` and TS/build config**

Create `app/frontend/package.json`:

```json
{
  "name": "hotel-revenue-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "lucide-react": "^0.427.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-hot-toast": "^2.4.1",
    "zustand": "^4.5.4"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.19",
    "postcss": "^8.4.40",
    "tailwindcss": "^3.4.7",
    "typescript": "^5.5.4",
    "vite": "^5.3.5"
  }
}
```

Create `app/frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `app/frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

Create `app/frontend/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
  build: { outDir: "dist" },
});
```

Create `app/frontend/tailwind.config.js`:

```js
/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        risk: { high: "#dc2626", medium: "#d97706", low: "#16a34a" },
      },
    },
  },
  plugins: [],
};
```

Create `app/frontend/postcss.config.js`:

```js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

- [ ] **Step 2: Write `index.html`, `main.tsx`, `index.css`, `vite-env.d.ts`**

Create `app/frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Hotel Revenue Manager</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `app/frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

Create `app/frontend/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html,
body,
#root {
  height: 100%;
}

body {
  @apply bg-slate-50 text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100;
}
```

Create `app/frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { Toaster } from "react-hot-toast";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
    <Toaster position="bottom-right" />
  </React.StrictMode>,
);
```

- [ ] **Step 3: Write `types.ts`, `store.ts`, `api.ts`**

Create `app/frontend/src/types.ts`:

```ts
export type RiskBand = "high" | "medium" | "low";

export type ActionType =
  | "reconfirmed"
  | "deposit_requested"
  | "overbooked_backup"
  | "released"
  | "note";

export const ACTION_TYPES: ActionType[] = [
  "reconfirmed",
  "deposit_requested",
  "overbooked_backup",
  "released",
  "note",
];

export interface Reservation {
  reservation_id: string;
  hotel: string;
  arrival_date: string;
  lead_time: number;
  adr: number;
  market_segment: string;
  adults: number;
  children: number;
  babies: number;
  deposit_type: string;
  customer_type: string;
  cancel_probability: number;
  risk_band: RiskBand;
  model_version: string | number;
  scored_at: string;
}

export interface Action {
  id: number;
  reservation_id: string;
  action_type: ActionType;
  note: string | null;
  acted_by: string | null;
  acted_at: string;
}

export interface Kpis {
  total: number;
  high_risk: number;
  medium_risk: number;
  low_risk: number;
  avg_cancel_probability: number | null;
  risk_band_mix: { risk_band: RiskBand; count: number }[];
}

export interface ReservationsPage {
  total: number;
  limit: number;
  offset: number;
  items: Reservation[];
}

export interface ReservationDetail {
  reservation: Reservation;
  actions: Action[];
}

export interface Filters {
  hotel?: string;
  risk_band?: RiskBand;
  market_segment?: string;
  min_lead_time?: number;
}
```

Create `app/frontend/src/store.ts`:

```ts
import { create } from "zustand";
import { persist } from "zustand/middleware";

type Theme = "light" | "dark";

interface UIState {
  theme: Theme;
  selectedId: string | null;
  setTheme: (t: Theme) => void;
  toggleTheme: () => void;
  setSelectedId: (id: string | null) => void;
}

const prefersDark =
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-color-scheme: dark)").matches;

export const useUI = create<UIState>()(
  persist(
    (set, get) => ({
      theme: prefersDark ? "dark" : "light",
      selectedId: null,
      setTheme: (t) => set({ theme: t }),
      toggleTheme: () => set({ theme: get().theme === "dark" ? "light" : "dark" }),
      setSelectedId: (id) => set({ selectedId: id }),
    }),
    { name: "hotel-app-ui", partialize: (s) => ({ theme: s.theme }) },
  ),
);
```

Create `app/frontend/src/api.ts`:

```ts
import type {
  Action,
  ActionType,
  Filters,
  Kpis,
  ReservationDetail,
  ReservationsPage,
} from "./types";

const BASE = "/api";

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function buildQuery(params: Filters & { limit?: number; offset?: number }): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  });
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  kpis: () => jsonFetch<Kpis>("/kpis"),
  reservations: (params: Filters & { limit?: number; offset?: number }) =>
    jsonFetch<ReservationsPage>(`/reservations${buildQuery(params)}`),
  reservation: (id: string) =>
    jsonFetch<ReservationDetail>(`/reservations/${encodeURIComponent(id)}`),
  createAction: (id: string, body: { action_type: ActionType; note?: string }) =>
    jsonFetch<Action>(`/reservations/${encodeURIComponent(id)}/actions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
```

- [ ] **Step 4: Write the app shell + Header (theme toggle)**

Create `app/frontend/src/components/Header.tsx`:

```tsx
import { Moon, Sun, TrendingUp } from "lucide-react";
import { useUI } from "../store";

export default function Header() {
  const theme = useUI((s) => s.theme);
  const toggleTheme = useUI((s) => s.toggleTheme);
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-6 w-6 text-indigo-600 dark:text-indigo-400" />
          <div>
            <h1 className="text-base font-semibold sm:text-lg">Hotel Revenue Manager</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              At-risk reservations &amp; actions
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label="Toggle theme"
          className="rounded-lg border border-slate-200 p-2 text-slate-600 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
        </button>
      </div>
    </header>
  );
}
```

Create `app/frontend/src/App.tsx`:

```tsx
import { useEffect } from "react";
import Header from "./components/Header";
import { useUI } from "./store";

export default function App() {
  const theme = useUI((s) => s.theme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  return (
    <div className="min-h-full">
      <Header />
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Loading dashboard…
        </p>
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Install deps and verify the build**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app/frontend && npm install && npm run build`
Expected: `npm install` completes, then `tsc -b && vite build` succeeds and writes `app/frontend/dist/` (with `index.html` + `assets/`). (If the sandbox blocks the npm registry, re-run with `required_permissions=["full_network"]`.)

- [ ] **Step 6: Commit**

```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27
git add app/frontend/package.json app/frontend/package-lock.json app/frontend/tsconfig.json app/frontend/tsconfig.node.json app/frontend/vite.config.ts app/frontend/tailwind.config.js app/frontend/postcss.config.js app/frontend/index.html app/frontend/src
git commit -m "feat(app): React+Vite+Tailwind scaffold with dark-mode toggle, API client, store"
```

---

### Task 5: Frontend — KPI header, filter bar, paginated reservations table

**Files:**
- Create: `app/frontend/src/format.ts`
- Create: `app/frontend/src/components/RiskBadge.tsx`
- Create: `app/frontend/src/components/KpiCards.tsx`
- Create: `app/frontend/src/components/FilterBar.tsx`
- Create: `app/frontend/src/components/ReservationsTable.tsx`
- Modify: `app/frontend/src/App.tsx`

**Interfaces:**
- Consumes `api`, `types`, `useUI` (Task 4).
- Produces UI components. `App` owns fetch state: `kpis`, `page` (items+total), `filters`, `offset`, `limit=50`, `loading`, `error`; refetches reservations when `filters`/`offset` change. Row click -> `setSelectedId` (drawer consumes it in Task 6).

- [ ] **Step 1: Write formatting helpers + RiskBadge**

Create `app/frontend/src/format.ts`:

```ts
import type { RiskBand } from "./types";

export const pct = (x: number | null | undefined) =>
  x === null || x === undefined ? "—" : `${(x * 100).toFixed(1)}%`;

export const money = (x: number | null | undefined) =>
  x === null || x === undefined
    ? "—"
    : x.toLocaleString(undefined, {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      });

export const riskBadgeClasses: Record<RiskBand, string> = {
  high: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  low: "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300",
};
```

Create `app/frontend/src/components/RiskBadge.tsx`:

```tsx
import type { RiskBand } from "../types";
import { riskBadgeClasses } from "../format";

export default function RiskBadge({ band }: { band: RiskBand }) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize ${riskBadgeClasses[band]}`}
    >
      {band}
    </span>
  );
}
```

- [ ] **Step 2: Write KpiCards**

Create `app/frontend/src/components/KpiCards.tsx`:

```tsx
import type { Kpis } from "../types";
import { pct } from "../format";

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export default function KpiCards({ kpis }: { kpis: Kpis | null }) {
  if (!kpis) {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-24 animate-pulse rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
          />
        ))}
      </div>
    );
  }
  const max = Math.max(kpis.high_risk, kpis.medium_risk, kpis.low_risk, 1);
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card label="Scored reservations" value={kpis.total.toLocaleString()} />
        <Card label="High risk" value={kpis.high_risk.toLocaleString()} />
        <Card
          label="Avg cancel probability"
          value={pct(kpis.avg_cancel_probability)}
        />
        <Card
          label="Risk mix (H / M / L)"
          value={`${kpis.high_risk} / ${kpis.medium_risk} / ${kpis.low_risk}`}
          hint="model-scored snapshot"
        />
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Risk-band distribution
        </p>
        <div className="space-y-2">
          {kpis.risk_band_mix.map((b) => (
            <div key={b.risk_band} className="flex items-center gap-3">
              <span className="w-16 text-sm capitalize">{b.risk_band}</span>
              <div className="h-3 flex-1 overflow-hidden rounded bg-slate-100 dark:bg-slate-800">
                <div
                  className={
                    b.risk_band === "high"
                      ? "h-full bg-risk-high"
                      : b.risk_band === "medium"
                        ? "h-full bg-risk-medium"
                        : "h-full bg-risk-low"
                  }
                  style={{ width: `${(b.count / max) * 100}%` }}
                />
              </div>
              <span className="w-16 text-right text-sm tabular-nums">
                {b.count.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Write FilterBar**

Create `app/frontend/src/components/FilterBar.tsx`:

```tsx
import type { Filters, RiskBand } from "../types";

interface Props {
  filters: Filters;
  onChange: (next: Filters) => void;
}

const RISK_BANDS: RiskBand[] = ["high", "medium", "low"];

export default function FilterBar({ filters, onChange }: Props) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch });
  const inputCls =
    "rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900";
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
        Hotel
        <select
          className={inputCls}
          value={filters.hotel ?? ""}
          onChange={(e) => set({ hotel: e.target.value || undefined })}
        >
          <option value="">All</option>
          <option value="City Hotel">City Hotel</option>
          <option value="Resort Hotel">Resort Hotel</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
        Risk band
        <select
          className={inputCls}
          value={filters.risk_band ?? ""}
          onChange={(e) =>
            set({ risk_band: (e.target.value || undefined) as RiskBand | undefined })
          }
        >
          <option value="">All</option>
          {RISK_BANDS.map((b) => (
            <option key={b} value={b} className="capitalize">
              {b}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
        Market segment
        <input
          className={inputCls}
          placeholder="e.g. Online TA"
          value={filters.market_segment ?? ""}
          onChange={(e) => set({ market_segment: e.target.value || undefined })}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-slate-500 dark:text-slate-400">
        Min lead time (days)
        <input
          type="number"
          min={0}
          className={`${inputCls} w-32`}
          value={filters.min_lead_time ?? ""}
          onChange={(e) =>
            set({
              min_lead_time: e.target.value ? Number(e.target.value) : undefined,
            })
          }
        />
      </label>
      <button
        type="button"
        onClick={() => onChange({})}
        className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 transition hover:bg-slate-100 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
      >
        Clear
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Write ReservationsTable**

Create `app/frontend/src/components/ReservationsTable.tsx`:

```tsx
import type { Reservation } from "../types";
import { money, pct } from "../format";
import RiskBadge from "./RiskBadge";

interface Props {
  items: Reservation[];
  loading: boolean;
  total: number;
  limit: number;
  offset: number;
  onSelect: (id: string) => void;
  onPage: (nextOffset: number) => void;
}

export default function ReservationsTable({
  items,
  loading,
  total,
  limit,
  offset,
  onSelect,
  onPage,
}: Props) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  const th =
    "px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400";
  const td = "px-3 py-2 text-sm";
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 dark:divide-slate-800">
          <thead className="bg-slate-50 dark:bg-slate-800/50">
            <tr>
              <th className={th}>Reservation</th>
              <th className={`${th} hidden sm:table-cell`}>Hotel</th>
              <th className={`${th} hidden md:table-cell`}>Arrival</th>
              <th className={`${th} hidden lg:table-cell`}>Lead</th>
              <th className={`${th} hidden lg:table-cell`}>ADR</th>
              <th className={`${th} hidden md:table-cell`}>Segment</th>
              <th className={th}>Cancel prob.</th>
              <th className={th}>Risk</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {loading &&
              items.length === 0 &&
              [0, 1, 2, 3, 4].map((i) => (
                <tr key={`sk-${i}`}>
                  <td className={td} colSpan={8}>
                    <div className="h-5 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
                  </td>
                </tr>
              ))}
            {!loading && items.length === 0 && (
              <tr>
                <td className={`${td} text-center text-slate-500`} colSpan={8}>
                  No reservations match these filters.
                </td>
              </tr>
            )}
            {items.map((r) => (
              <tr
                key={r.reservation_id}
                onClick={() => onSelect(r.reservation_id)}
                className="cursor-pointer transition hover:bg-slate-50 dark:hover:bg-slate-800/50"
              >
                <td className={`${td} font-mono text-xs`}>
                  {r.reservation_id.slice(0, 12)}…
                </td>
                <td className={`${td} hidden sm:table-cell`}>{r.hotel}</td>
                <td className={`${td} hidden md:table-cell`}>{r.arrival_date}</td>
                <td className={`${td} hidden lg:table-cell tabular-nums`}>{r.lead_time}</td>
                <td className={`${td} hidden lg:table-cell tabular-nums`}>{money(r.adr)}</td>
                <td className={`${td} hidden md:table-cell`}>{r.market_segment}</td>
                <td className={`${td} tabular-nums`}>{pct(r.cancel_probability)}</td>
                <td className={td}>
                  <RiskBadge band={r.risk_band} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-slate-200 px-3 py-2 text-sm dark:border-slate-800">
        <span className="text-slate-500 dark:text-slate-400">
          {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => onPage(Math.max(0, offset - limit))}
            className="rounded-lg border border-slate-200 px-3 py-1 disabled:opacity-40 dark:border-slate-700"
          >
            Prev
          </button>
          <button
            type="button"
            disabled={to >= total}
            onClick={() => onPage(offset + limit)}
            className="rounded-lg border border-slate-200 px-3 py-1 disabled:opacity-40 dark:border-slate-700"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Wire fetch state into `App.tsx`**

Replace `app/frontend/src/App.tsx` with:

```tsx
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";
import Header from "./components/Header";
import KpiCards from "./components/KpiCards";
import FilterBar from "./components/FilterBar";
import ReservationsTable from "./components/ReservationsTable";
import { api } from "./api";
import type { Filters, Kpis, ReservationsPage } from "./types";
import { useUI } from "./store";

const LIMIT = 50;

export default function App() {
  const theme = useUI((s) => s.theme);
  const setSelectedId = useUI((s) => s.setSelectedId);

  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [page, setPage] = useState<ReservationsPage | null>(null);
  const [filters, setFilters] = useState<Filters>({});
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  useEffect(() => {
    api.kpis().then(setKpis).catch((e) => toast.error(`KPIs: ${e.message}`));
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    api
      .reservations({ ...filters, limit: LIMIT, offset })
      .then(setPage)
      .catch((e) => toast.error(`Reservations: ${e.message}`))
      .finally(() => setLoading(false));
  }, [filters, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const onFilterChange = (next: Filters) => {
    setOffset(0);
    setFilters(next);
  };

  return (
    <div className="min-h-full">
      <Header />
      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6 sm:px-6">
        <KpiCards kpis={kpis} />
        <FilterBar filters={filters} onChange={onFilterChange} />
        <ReservationsTable
          items={page?.items ?? []}
          loading={loading}
          total={page?.total ?? 0}
          limit={LIMIT}
          offset={offset}
          onSelect={setSelectedId}
          onPage={setOffset}
        />
      </main>
    </div>
  );
}
```

- [ ] **Step 6: Verify the build**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app/frontend && npm run build`
Expected: `tsc -b && vite build` succeeds with no type errors; `dist/` refreshed.

- [ ] **Step 7: Commit**

```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27
git add app/frontend/src
git commit -m "feat(app): KPI header, filter bar, paginated reservations table"
```

---

### Task 6: Frontend — reservation detail drawer + action write-back form

**Files:**
- Create: `app/frontend/src/components/ActionForm.tsx`
- Create: `app/frontend/src/components/ReservationDrawer.tsx`
- Modify: `app/frontend/src/App.tsx`

**Interfaces:**
- Consumes `api`, `types` (`ACTION_TYPES`), `useUI` (`selectedId`, `setSelectedId`), `format`, `RiskBadge`.
- `ReservationDrawer` opens when `selectedId` is set: fetches `api.reservation(id)`, renders booking facts + prior actions + `ActionForm`; on a successful action it refetches the detail and calls `onActed` (App refreshes the list + KPIs). Responsive: right-side drawer on `sm+`, full-screen sheet on mobile.

- [ ] **Step 1: Write ActionForm**

Create `app/frontend/src/components/ActionForm.tsx`:

```tsx
import { useState } from "react";
import toast from "react-hot-toast";
import { api } from "../api";
import { ACTION_TYPES, type ActionType } from "../types";

const LABELS: Record<ActionType, string> = {
  reconfirmed: "Reconfirmed",
  deposit_requested: "Deposit requested",
  overbooked_backup: "Overbooking backup",
  released: "Released",
  note: "Note",
};

export default function ActionForm({
  reservationId,
  onCreated,
}: {
  reservationId: string;
  onCreated: () => void;
}) {
  const [actionType, setActionType] = useState<ActionType>("reconfirmed");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.createAction(reservationId, {
        action_type: actionType,
        note: note.trim() || undefined,
      });
      toast.success("Action recorded");
      setNote("");
      onCreated();
    } catch (err) {
      toast.error(`Failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const inputCls =
    "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900";

  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">
        Action
        <select
          className={`mt-1 ${inputCls}`}
          value={actionType}
          onChange={(e) => setActionType(e.target.value as ActionType)}
        >
          {ACTION_TYPES.map((a) => (
            <option key={a} value={a}>
              {LABELS[a]}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400">
        Note (optional)
        <textarea
          className={`mt-1 ${inputCls}`}
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Context for this action…"
        />
      </label>
      <button
        type="submit"
        disabled={saving}
        className="w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:opacity-50"
      >
        {saving ? "Recording…" : "Record action"}
      </button>
    </form>
  );
}
```

- [ ] **Step 2: Write ReservationDrawer**

Create `app/frontend/src/components/ReservationDrawer.tsx`:

```tsx
import { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import toast from "react-hot-toast";
import { api } from "../api";
import type { ReservationDetail } from "../types";
import { money, pct } from "../format";
import RiskBadge from "./RiskBadge";
import ActionForm from "./ActionForm";

interface Props {
  reservationId: string;
  onClose: () => void;
  onActed: () => void;
}

function Fact({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-xs text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-sm font-medium">{value}</dd>
    </div>
  );
}

export default function ReservationDrawer({ reservationId, onClose, onActed }: Props) {
  const [detail, setDetail] = useState<ReservationDetail | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .reservation(reservationId)
      .then(setDetail)
      .catch((e) => toast.error(`Detail: ${e.message}`))
      .finally(() => setLoading(false));
  }, [reservationId]);

  useEffect(() => {
    load();
  }, [load]);

  const onCreated = () => {
    load();
    onActed();
  };

  const r = detail?.reservation;

  return (
    <div className="fixed inset-0 z-30">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <aside className="absolute inset-0 flex flex-col bg-white shadow-xl dark:bg-slate-900 sm:inset-y-0 sm:right-0 sm:left-auto sm:w-full sm:max-w-md">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800">
          <h2 className="text-sm font-semibold">Reservation detail</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 space-y-6 overflow-y-auto px-4 py-4">
          {loading && (
            <div className="h-40 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
          )}

          {r && (
            <>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-slate-500">{r.reservation_id}</span>
                <RiskBadge band={r.risk_band} />
              </div>
              <dl className="grid grid-cols-2 gap-3">
                <Fact label="Hotel" value={r.hotel} />
                <Fact label="Arrival" value={r.arrival_date} />
                <Fact label="Cancel probability" value={pct(r.cancel_probability)} />
                <Fact label="Lead time (days)" value={r.lead_time} />
                <Fact label="ADR" value={money(r.adr)} />
                <Fact label="Market segment" value={r.market_segment} />
                <Fact label="Customer type" value={r.customer_type} />
                <Fact label="Deposit type" value={r.deposit_type} />
                <Fact label="Party (A/C/B)" value={`${r.adults}/${r.children}/${r.babies}`} />
                <Fact label="Model version" value={String(r.model_version)} />
              </dl>

              <div>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Record an action
                </h3>
                <ActionForm reservationId={r.reservation_id} onCreated={onCreated} />
              </div>

              <div>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  Prior actions
                </h3>
                {detail!.actions.length === 0 ? (
                  <p className="text-sm text-slate-500">No actions recorded yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {detail!.actions.map((a) => (
                      <li
                        key={a.id}
                        className="rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-800"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium capitalize">
                            {a.action_type.replace(/_/g, " ")}
                          </span>
                          <span className="text-xs text-slate-400">
                            {new Date(a.acted_at).toLocaleString()}
                          </span>
                        </div>
                        {a.note && <p className="mt-1 text-slate-600 dark:text-slate-300">{a.note}</p>}
                        {a.acted_by && (
                          <p className="mt-1 text-xs text-slate-400">by {a.acted_by}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
```

- [ ] **Step 3: Render the drawer from `App.tsx`**

Edit `app/frontend/src/App.tsx`: add the import, read `selectedId`, refresh KPIs + list after an action, and render the drawer when a reservation is selected.

Add the import near the other component imports:

```tsx
import ReservationDrawer from "./components/ReservationDrawer";
```

In the component body, add `selectedId` from the store and a KPI refresher:

```tsx
  const selectedId = useUI((s) => s.selectedId);

  const refreshKpis = useCallback(() => {
    api.kpis().then(setKpis).catch((e) => toast.error(`KPIs: ${e.message}`));
  }, []);
```

Replace the initial KPI `useEffect` body to reuse it:

```tsx
  useEffect(() => {
    refreshKpis();
  }, [refreshKpis]);
```

Then, just before the final closing `</div>` of the returned JSX, render the drawer:

```tsx
      {selectedId && (
        <ReservationDrawer
          reservationId={selectedId}
          onClose={() => setSelectedId(null)}
          onActed={() => {
            load();
            refreshKpis();
          }}
        />
      )}
```

- [ ] **Step 4: Verify the build**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app/frontend && npm run build`
Expected: `tsc -b && vite build` succeeds with no type errors; `dist/` refreshed with the full UI.

- [ ] **Step 5: Commit**

```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27
git add app/frontend/src
git commit -m "feat(app): reservation detail drawer + action write-back form"
```

---

### Task 7: Bundle wiring — `apps` resource + `app.yaml`

**Files:**
- Create: `app/app.yaml`
- Create: `resources/hotel_app.yml`

**Interfaces:**
- Declares the app in the DABs bundle. `databricks bundle validate -t dev` must pass. The app is uploaded from `../app` (bundle deploy respects `app/.gitignore`, so `node_modules`/`.venv` are excluded and `frontend/dist` — not ignored — is included).

- [ ] **Step 1: Write `app/app.yaml`**

```yaml
# Databricks App runtime config. The `database` resource declared in
# resources/hotel_app.yml injects PGHOST/PGUSER/PGPORT/PGDATABASE at runtime;
# DATABRICKS_INSTANCE_NAME + PGDATABASE below back the db.py fallback path.
command:
  - "python"
  - "-m"
  - "uvicorn"
  - "app:app"
  - "--host"
  - "0.0.0.0"
  - "--port"
  - "8000"

env:
  - name: DATABRICKS_INSTANCE_NAME
    value: "hotel-lakebase"
  - name: PGDATABASE
    value: "hotel"
```

- [ ] **Step 2: Write `resources/hotel_app.yml`**

```yaml
resources:
  apps:
    hotel_revenue_app:
      name: hotel-revenue-app
      description: >-
        Revenue-manager app: triage at-risk reservations from the Lakebase serving
        layer and record operational actions (write-back to public.reservation_action).
      source_code_path: ../app
      resources:
        - name: lakebase
          database:
            instance_name: hotel-lakebase
            database_name: hotel
            permission: CAN_CONNECT_AND_CREATE
```

- [ ] **Step 3: Validate the bundle**

Run (outside the sandbox — needs the workspace API): `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && databricks bundle validate -t dev` with `required_permissions=["all"]`.
Expected: validation succeeds and the summary lists the `hotel_revenue_app` app alongside the existing pipeline/jobs/Lakebase resources. If validation reports an unknown key on the `database` resource (schema drift), adjust the key names to match the error (e.g. `permission` enum) and re-run until it passes — this is the only place the app-resource schema is asserted against the live CLI.

- [ ] **Step 4: Commit**

```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27
git add app/app.yaml resources/hotel_app.yml
git commit -m "feat(app): declare hotel_revenue_app as a DABs apps resource"
```

---

### Task 8: Deploy, grant, verify, and capture evidence (orchestrator)

> **Orchestrator task.** These steps use the Databricks CLI / MCP + Chrome DevTools MCP and touch the live workspace — run them in the main session (not a code subagent), same as the prior Lakebase/Genie deploy+verify tasks. CLI/psql steps run **outside the sandbox** (`required_permissions=["all"]`). The `hotel-lakebase` instance must be **running**.

**Files:**
- Create: `docs/evidence/app-run.md`
- Create: `docs/evidence/img/app-list-light.png`, `app-list-dark.png`, `app-detail-action.png` (Chrome DevTools screenshots)

**Interfaces:**
- Consumes the deployed app + its service principal; produces the evidence doc with screenshots, a write-back round-trip proof, and a KPI parity spot-check.

- [ ] **Step 1: Ensure the Lakebase instance is running**

Run: `databricks database get-database-instance hotel-lakebase -o json | jq '.state'` (profile `DEFAULT`, `required_permissions=["all"]`).
If `STOPPED`, start it: `databricks database update-database-instance hotel-lakebase --json '{"stopped": false}'` and poll `get-database-instance` until `.state` is `AVAILABLE`.

- [ ] **Step 2: Local smoke test (fast dev loop, owner identity)**

Locally the connection runs as the CLI user (table owner) so no extra grants are needed.
```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app/frontend && npm run build
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27/app && \
  DATABRICKS_PROFILE=DEFAULT uv run uvicorn app:app --port 8000
```
With the server up, verify via the Chrome DevTools MCP against `http://localhost:8000`:
- `navigate_page` → `take_screenshot` of the reservations list.
- `list_console_messages` → expect no errors.
- Toggle dark mode (click the header button) → screenshot.
- Apply a filter (e.g. risk band = high) → the table/count updates.
- Click a row → the detail drawer opens; submit an action (e.g. "Reconfirmed" + note) → success toast, and the action appears under "Prior actions" (**write-back round-trip**).
Record the app's `/api/kpis` response (from the Network panel) for the parity check in Step 6.

- [ ] **Step 3: Deploy via the bundle**

Run (outside sandbox): `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && databricks bundle deploy -t dev` with `required_permissions=["all"]`.
Then confirm: `databricks apps get hotel-revenue-app -o json | jq '{name, url, service_principal_client_id, compute_status: .compute_status.state}'`. Record the app `url` and `service_principal_client_id`.

- [ ] **Step 4: Grant the app service principal its Postgres privileges (one-time)**

The app SP connects to Postgres as a role named by its client id. Grant it read on the synced table and read/insert on the write-back table. Connect to the `hotel` DB as the CLI user (table owner) with an OAuth token:
```bash
SP="<service_principal_client_id from Step 3>"
HOST=$(databricks database get-database-instance hotel-lakebase -o json | jq -r '.read_write_dns')
TOKEN=$(databricks database generate-database-credential --json '{"instance_names":["hotel-lakebase"]}' -o json | jq -r '.token')
EMAIL=$(databricks current-user me -o json | jq -r '.userName')
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=hotel user=$EMAIL sslmode=require" -v sp="$SP" <<'SQL'
GRANT USAGE ON SCHEMA hotel_booking_dev TO :"sp";
GRANT SELECT ON hotel_booking_dev.reservation_risk_serving_synced TO :"sp";
GRANT USAGE ON SCHEMA public TO :"sp";
GRANT SELECT, INSERT ON public.reservation_action TO :"sp";
GRANT USAGE, SELECT ON SEQUENCE public.reservation_action_id_seq TO :"sp";
SQL
```
(Run outside the sandbox. If the SP role does not yet exist, redeploy/start the app once so Databricks provisions the role for the attached database resource, then re-run the grants.)

- [ ] **Step 5: Remote smoke test**

Start the app if needed (`databricks apps start hotel-revenue-app`), then via Chrome DevTools MCP navigate to the app `url`: screenshot the list, confirm no console errors, and confirm KPIs + table load (proves the SP grants work). Check `<app-url>/logz` for clean startup (`pool.open` succeeded). Save the light + dark list screenshots and the detail+action screenshot to `docs/evidence/img/`.

- [ ] **Step 6: KPI parity spot-check**

Compare the app's `/api/kpis` numbers against a direct query:
```bash
PGPASSWORD="$TOKEN" psql "host=$HOST port=5432 dbname=hotel user=$EMAIL sslmode=require" -c \
"SELECT count(*) AS total,
        count(*) FILTER (WHERE risk_band='high') AS high,
        round(avg(cancel_probability)::numeric, 4) AS avg_prob
 FROM hotel_booking_dev.reservation_risk_serving_synced;"
```
Expected: `total = 87395`, `high = 10238` (from the Lakebase evidence), matching the app KPI header.

- [ ] **Step 7: Write `docs/evidence/app-run.md`**

Create the doc with this structure, filling every bracket from the actual run and embedding the screenshots:

```markdown
# Evidence — Hotel Revenue-Manager Databricks App (dev)

**Workspace:** fevm-fe-bar-ecastillo
**App:** hotel-revenue-app — [app url]
**Service principal:** [service_principal_client_id]
**Data plane:** Lakebase instance hotel-lakebase, DB `hotel`
  (read `hotel_booking_dev.reservation_risk_serving_synced`, write `public.reservation_action`)
**Run date:** 2026-09-30

## UI (modern, responsive, light/dark)

![Reservations list (light)](img/app-list-light.png)
![Reservations list (dark)](img/app-list-dark.png)
![Detail drawer + action write-back](img/app-detail-action.png)

## Write-back round-trip

Recorded an action via the UI on reservation `[id]`:
- Submitted: action_type=`[type]`, note=`[note]` → success toast.
- Re-fetched detail → the action appears under "Prior actions" (acted_by=`[acted_by]`).
- Postgres confirmation:
  ```
  [psql SELECT ... FROM public.reservation_action WHERE reservation_id='[id]' output]
  ```

## KPI parity (app vs direct SQL)

App `/api/kpis`: total=[..], high_risk=[..], avg_cancel_probability=[..]
Direct psql: total=87395, high=10238, avg_prob=[..]
Match: [yes/no + note]

## Deploy notes

- Declared as DABs `apps` resource (`resources/hotel_app.yml`); shipped by `databricks bundle deploy -t dev`.
- Connection uses the classic GA path (`w.database.generate_database_credential`,
  `read_write_dns`) with runtime-injected PG env (Approach A) + SDK fallback (Approach B).
- One-time SP grants applied on `hotel` (SELECT on the synced table; SELECT/INSERT on
  reservation_action + its sequence).
- Instance hotel-lakebase must be running; set `stopped: true` when idle.
```

- [ ] **Step 8: Verify the evidence doc has no unfilled placeholders**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && ! grep -nE "\[app url\]|\[id\]|\[type\]|\[note\]|\[acted_by\]|\[\.\.\]|\[service_principal_client_id\]" docs/evidence/app-run.md && echo "evidence doc filled"`
Expected: `evidence doc filled`.

- [ ] **Step 9: Commit**

```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27
git add docs/evidence/app-run.md docs/evidence/img
git commit -m "docs(app): add deploy + write-back + KPI-parity evidence with screenshots"
```

---

### Task 9: README — document the App slice + push

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes the app `url` + evidence (Task 8). Produces the README App section and ticks the capstone deliverable.

- [ ] **Step 1: Add an App section to the README**

Add a "Databricks App — revenue-manager UI" subsection near the Lakebase/Genie docs. Include:
- What it does: triage at-risk reservations from Lakebase + record actions (write-back); modern responsive UI with light/dark.
- Architecture: FastAPI + React (Vite/Tailwind), single Lakebase Postgres data plane, classic GA-instance auth (A+B fallback), deployed as the `resources/hotel_app.yml` `apps` resource.
- Artifacts: `app/` (backend `server/`, `frontend/`), `resources/hotel_app.yml`, `docs/evidence/app-run.md`.
- Run/deploy: local (`uv run uvicorn app:app` + `npm run dev`), deploy (`databricks bundle deploy -t dev`), logs at `<app-url>/logz`; note the one-time SP GRANT and that `hotel-lakebase` must be running.
- Honest limit: KPIs are model-scored-snapshot metrics; no occupancy/RevPAR (inventory not in data).

- [ ] **Step 2: Tick the capstone deliverable**

Update the Deliverables line `- [ ] The build (code, notebooks with outputs, app, Genie room) (Genie room done)` to reflect the app is now done (e.g. mark it `- [x]` / note "app + Genie room done").

- [ ] **Step 3: Verify the README references the app**

Run: `cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && grep -niE "revenue-manager|hotel_app.yml|app-run.md" README.md && echo "README updated"`
Expected: matching lines + `README updated`.

- [ ] **Step 4: Commit and push**

```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27
git add README.md
git commit -m "docs(app): document Databricks App slice in README"
git push origin main
```
(Push uses the `jestebanc16` remote with `required_permissions=["full_network","git_write"]` + smart-mode approval, per repo convention.)

---

## Self-review notes

- **Spec coverage:** scope/three regions (§1) → Tasks 5–6; single Lakebase data plane (§2/§3) → Tasks 1–3; exact schemas (§3) → Global Constraints + Task 1 constants + Task 8 parity; API surface (§4) → Task 3; modern/responsive/light-dark UI (§5) → Tasks 4–6; dual-mode auth + forwarded-identity `acted_by` + SP grants (§6) → Task 2 (`pick_acted_by`) + Task 8 Step 4; bundle `apps` resource + A/B connection (§7) → Tasks 2 & 7; error handling (§8) → Task 3 (404/400/503) + fail-fast lifespan; tight query-layer unit tests + manual Chrome DevTools verification + `app-run.md` (§9) → Tasks 1–3 tests + Task 8; data flow (§10) → Tasks 2–3; out-of-scope (§11) honored (no AI/warehouse/edit-delete); risks (§12) → A/B fallback (Task 2), SP grants (Task 8 Step 4), instance-running (Task 8 Step 1), server-side paging (Task 1/5).
- **Placeholder scan:** the only bracketed placeholders are inside the Task 8 evidence-doc template, which Step 8 explicitly checks are filled; no `TBD/TODO` in code steps.
- **Type/name consistency:** `queries.*` names defined in Task 1 are consumed unchanged in Task 3; `resolve_conn_params`/`pick_acted_by`/`resolve_acted_by`/`get_pool`/`open_pool`/`close_pool` defined in Task 2 and used in Task 3; `serialize.jsonable` defined + used in Task 3; the HTTP response shapes in Task 3 match the TS `types.ts` (Task 4) consumed by `api.ts` and the components (Tasks 5–6); `useUI` (`theme`, `selectedId`, `setSelectedId`, `toggleTheme`) defined in Task 4 store and used in Tasks 4–6; `ACTION_TYPES` defined in Task 4 types and used in Task 6.
- **Deviation from the databricks-apps skill (intentional):** classic GA Database-Instance auth (`w.database...` + `read_write_dns`), not the Autoscaling `w.postgres`/`ENDPOINT_NAME` pattern — called out in Global Constraints and Task 2.
