# Design — Hotel Revenue-Manager App (Databricks App capstone slice)

**Date:** 2026-09-30
**Workspace:** `fevm-fe-bar-ecastillo` · bundle `hotel_booking_ingest` (dev target: catalog
`fe_bar_ecastillo_catalog`, schema `hotel_booking_dev`)
**Status:** Approved design → ready for implementation plan

## 1. Purpose & scope

A single-purpose internal tool for a **revenue manager** to triage at-risk reservations and
record an operational action against them. It is the capstone surface of the project, sitting on
the Lakebase serving layer built in the prior slice.

Three regions on one screen:

- **KPI header** — portfolio snapshot derived from the risk table (total scored, count high-risk,
  average cancel probability, risk-band mix).
- **At-risk reservations table** — server-side filtered + paginated list (default: highest cancel
  probability first) of scored reservations with booking detail.
- **Reservation detail + action panel** — opens for a selected row; shows booking detail + prior
  actions, and an action form that **writes** to `public.reservation_action`.

This exercises the full Lakebase **read + write-back loop** — the point of the serving slice.

### Honest limit (carried from the data layer)

There is **no true occupancy / RevPAR** — room inventory is not in the dataset. The KPIs are
model-scored-snapshot metrics (a single scoring batch, `model_version = 1`), and the UI labels
them as such. No historical-actuals / gold path is used (see §11 out-of-scope).

## 2. Architecture

- **Backend** — FastAPI (Python), packaged with `uv` (`pyproject.toml` + `uv.lock`). Postgres
  access via `psycopg` + `psycopg_pool`. Sync `def` route handlers (FastAPI runs them in a
  threadpool, the correct pattern for psycopg sync connections). Connection pool opened in the
  FastAPI `lifespan` with `pool.open(wait=True, timeout=30.0)` (fail-fast if the DB is
  unreachable).
- **Frontend** — React + TypeScript (Vite), Tailwind CSS, `lucide-react` icons, minimal Zustand
  store. Built to `frontend/dist` and served by FastAPI as static assets + SPA fallback.
- **Deploy** — DABs `apps` resource (`resources/hotel_app.yml`), shipped by
  `databricks bundle deploy`, consistent with the rest of the project (pipeline, jobs, Lakebase
  all live in the bundle).
- **Data plane** — a single Lakebase Postgres connection to logical DB `hotel` on instance
  `hotel-lakebase`. No SQL warehouse, no second data path.

### Repo layout (under the currently-empty `app/`)

```
app/
├── app.yaml              # Databricks app config (command + env)
├── app.py                # FastAPI entry: lifespan, routers, static SPA mount
├── pyproject.toml        # backend deps (uv-native)
├── uv.lock
├── server/
│   ├── __init__.py
│   ├── config.py         # dual-mode auth (IS_DATABRICKS_APP), identity helpers
│   ├── db.py             # Lakebase pool + OAuthConnection (GA instance) + B-fallback
│   ├── queries.py        # pure SQL-builder / param-parsing functions (unit-tested)
│   └── routes/
│       ├── __init__.py
│       ├── health.py
│       ├── kpis.py
│       ├── reservations.py
│       └── actions.py
├── tests/
│   └── test_queries.py   # pure-function unit tests (no DB)
├── frontend/             # Vite React-TS app → dist/
│   ├── package.json
│   ├── vite.config.ts    # dev proxy /api → :8000
│   ├── tailwind.config.js
│   └── src/
└── .gitignore            # exclude node_modules, .venv, __pycache__; KEEP frontend/dist
```

## 3. Data model & queries (Lakebase Postgres, DB `hotel`)

Both tables live in the `hotel` database and are joinable.

### Read — `hotel_booking_dev.reservation_risk_serving_synced` (SNAPSHOT synced, 87,395 rows)

Columns (confirmed from `build_serving_table.py`):

| Column | Type | Notes |
|---|---|---|
| `reservation_id` | text | PK (content hash), `NOT NULL` |
| `hotel` | text | |
| `arrival_date` | date | |
| `lead_time` | int | days |
| `adr` | double | average daily rate |
| `market_segment` | text | |
| `adults`, `children`, `babies` | int | |
| `deposit_type` | text | |
| `customer_type` | text | |
| `cancel_probability` | double | model score 0–1 |
| `risk_band` | text | `high` / `medium` / `low` |
| `model_version` | text/int | `1` (single batch) |
| `scored_at` | timestamp | scoring timestamp |

### Write — `public.reservation_action` (append-only; confirmed from `provision_writeback.py`)

```
id             BIGSERIAL PRIMARY KEY
reservation_id TEXT NOT NULL
action_type    TEXT NOT NULL CHECK (action_type IN
                 ('reconfirmed','deposit_requested','overbooked_backup','released','note'))
note           TEXT
acted_by       TEXT
acted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
```
Index `ix_reservation_action_res (reservation_id, acted_at DESC)` already exists.

### Query patterns (all parameterized with psycopg `%s`; no string interpolation)

- **KPIs** — `COUNT(*)`, `COUNT(*) FILTER (WHERE risk_band='high')`, `AVG(cancel_probability)`,
  and a `GROUP BY risk_band` count, over the synced table.
- **List** — `WHERE` built from optional filters (`hotel`, `risk_band`, `market_segment`,
  `min_lead_time`), `ORDER BY cancel_probability DESC`, `LIMIT`/`OFFSET` paging; a companion
  `COUNT(*)` with the same `WHERE` for total.
- **Detail** — one row by `reservation_id`, plus its prior actions
  (`SELECT ... FROM public.reservation_action WHERE reservation_id = %s ORDER BY acted_at DESC`).
- **Insert action** — `INSERT INTO public.reservation_action (reservation_id, action_type, note,
  acted_by) VALUES (%s,%s,%s,%s) RETURNING id, acted_at`.

## 4. API surface

| Method / path | Purpose |
|---|---|
| `GET /api/health` | Pool/DB liveness (used by lifespan + smoke test) |
| `GET /api/kpis` | Portfolio aggregates (counts, avg probability, risk-band mix) |
| `GET /api/reservations?hotel=&risk_band=&market_segment=&min_lead_time=&limit=&offset=` | Paged list + total count |
| `GET /api/reservations/{reservation_id}` | Booking detail + prior actions |
| `POST /api/reservations/{reservation_id}/actions` | Body `{action_type, note}`; validates `action_type`; inserts with server-derived `acted_by`; returns created row |

Validation: `action_type` is checked server-side against the same five values as the DB CHECK
constraint (fail fast with 400 before hitting Postgres). `limit` is capped (e.g. ≤ 200) and
defaults sensibly; `offset` ≥ 0.

## 5. Frontend UX — modern, responsive, theme-toggleable

- **Visual style** — clean modern dashboard: Tailwind design tokens, soft shadows, rounded cards,
  generous spacing, a restrained accent color, `lucide-react` icons, subtle hover/transition
  states. Risk bands use consistent semantic colors (high = red, medium = amber, low = green) that
  hold up in both themes.
- **Light/dark toggle** — a header toggle (sun/moon) using Tailwind's `class` dark mode; choice
  persisted to `localStorage` and initialized from `prefers-color-scheme`. All surfaces, text, the
  chart, and risk-band colors have dark variants.
- **Responsive** — mobile-first with Tailwind breakpoints. Wide screens: KPI cards in a row, filter
  bar inline, full table, detail as a right-side drawer. Narrow screens: KPI cards stack/scroll,
  filters collapse into a compact control, table reduces to essential columns (or card-style rows),
  and detail opens as a full-screen sheet instead of a side drawer.
- **Layout** — header (title + theme toggle) → KPI cards row (with a small risk-band bar chart) →
  filter bar → paginated reservations table → detail drawer/sheet containing booking facts, the
  prior-actions list, and the action form (`action_type` select + note textarea + submit). Toast on
  success/failure; explicit loading / empty / error states throughout. No routing beyond the drawer.

## 6. Auth & identity

- **Dual-mode** (`config.py`): `IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))`.
  In-app → `WorkspaceClient()` (auto-injected service-principal creds); locally →
  `WorkspaceClient(profile=os.environ.get("DATABRICKS_PROFILE","DEFAULT"))`.
- **`acted_by` attribution** — in-app, read the forwarded end-user identity header
  (`X-Forwarded-Email`, fallback `X-Forwarded-Preferred-Username`); locally, the CLI user email;
  final fallback `"local-dev"`. There is **no on-behalf-of database auth** — the app SP owns the
  Postgres connection; the acting user is captured as data only.
- **Postgres grants (one-time setup, tracked risk)** — the app **service principal** needs a
  Postgres role on `hotel-lakebase` with `SELECT` on
  `hotel_booking_dev.reservation_risk_serving_synced` and `SELECT, INSERT` on
  `public.reservation_action`. Documented as a one-time psql `GRANT` step run by the deployer
  (OAuth token via `databricks database generate-database-credential`), because the write-back
  table was created by a human identity in the prior slice.

## 7. Bundle wiring (`resources/hotel_app.yml`)

- `apps.hotel_revenue_app`:
  - `source_code_path` → the bundle-synced `app/` directory.
  - a `database` resource: `{ instance_name: hotel-lakebase, database_name: hotel,
    permission: CAN_CONNECT }` (Approach A — the app grabs the grant declaratively; the runtime
    injects `PGHOST`/`PGUSER`/`PGPORT`/`PGDATABASE`).
- `app.yaml`:
  - `command`: `python -m uvicorn app:app --host 0.0.0.0 --port 8000`.
  - env: `DATABRICKS_INSTANCE_NAME=hotel-lakebase`, `PGDATABASE=hotel` (belt-and-suspenders for
    the fallback), and any non-secret config.
- **Connection auth — Approach A with B fallback** (`db.py`): a psycopg `ConnectionPool` with an
  `OAuthConnection` subclass whose `connect()` mints a fresh token per connection via
  `w.database.generate_database_credential(request_id=str(uuid4()),
  instance_names=[INSTANCE])`; `max_lifetime=2700` (recycle before the 1-hour token expiry).
  Host/user come from injected `PGHOST`/`PGUSER` when present (**A**); if `PGHOST` is absent,
  fall back to `w.database.get_database_instance(INSTANCE).read_write_dns` (**B**). This is the
  **classic GA Database Instance** path — NOT the Autoscaling `w.postgres.generate_database_credential(endpoint=...)`
  / `ENDPOINT_NAME` pattern in the databricks-apps skill.
- **Operational note** — instance `hotel-lakebase` (CU_1) must be **running** (we set
  `stopped: true` when idle) for the app to serve.

## 8. Error handling

- Pool open fails fast in lifespan; `GET /api/health` reports DB reachability.
- `404` on unknown `reservation_id`; `400` on invalid `action_type` (mirrors the CHECK
  constraint); `503` when the DB is unreachable.
- Frontend surfaces errors via toast + inline states; explicit loading / empty states.
- Writes are append-only → no concurrency, edit, or delete logic.

## 9. Testing & verification

- **Automated (kept tight)** — unit tests for the pure `queries.py` builders and filter/param
  parsing (mirrors the Genie slice's testable-pure-Python approach). No DB in unit tests; assert
  generated SQL text + parameter tuples and the 400-on-bad-`action_type` guard.
- **Manual** — local dev-loop with Chrome DevTools MCP (screenshots, console-error check,
  click-through of filter → row → action), then a deployed smoke test against the app URL and
  `/logz`.
- **Evidence** — `docs/evidence/app-run.md`: screenshots (list, filtered, detail + action, both
  themes), a **write-back round-trip proof** (POST an action → read it back via
  `GET /api/reservations/{id}`), and a **KPI parity spot-check** (app `/api/kpis` numbers vs a
  direct Postgres/`execute_sql` count). Update the README app section and tick the capstone
  deliverable checkbox.

## 10. Data flow (summary)

```
Browser (React SPA)
  │  GET /api/kpis, /api/reservations, /api/reservations/{id}
  │  POST /api/reservations/{id}/actions
  ▼
FastAPI (sync routes, threadpool)
  │  psycopg_pool.ConnectionPool → OAuthConnection (fresh token/conn)
  ▼
Lakebase Postgres (DB "hotel", instance hotel-lakebase)
     read  → hotel_booking_dev.reservation_risk_serving_synced
     write → public.reservation_action
```

## 11. Out of scope (YAGNI)

- No AI / Genie embed, no Foundation-Model or serving-endpoint what-if scoring.
- No gold / SQL-warehouse historical-actuals path (KPIs come only from the synced risk table).
- No action edit or delete (append-only).
- No realtime auto-refresh / websockets.
- No auth beyond forwarded end-user identity for attribution.

## 12. Key risks & mitigations

1. **Classic-instance `database`-resource env injection** is less battle-tested than Autoscaling →
   mitigated by the Approach-B fallback in `db.py` (build conninfo from `read_write_dns`).
2. **SP Postgres grants** must exist before the app can read/write → one-time documented `GRANT`
   step (§6).
3. **Instance stopped when idle** → must be running to demo/deploy; note in README + evidence.
4. **Pagination over 87k rows** → always server-side `LIMIT`/`OFFSET`; never load the full table
   into the client.
```
