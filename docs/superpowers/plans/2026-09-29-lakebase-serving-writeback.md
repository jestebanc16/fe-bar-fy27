# Lakebase serving + write-back — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve per-reservation cancellation risk from Lakebase (Postgres) via a SNAPSHOT synced table, and give the future app an append-only `reservation_action` write-back table — all declared in the DAB bundle.

**Architecture:** A new bundle Database Instance (`CU_1`) hosts a logical Postgres DB `hotel`. A three-task serverless job (`hotel_lakebase_sync`) builds a denormalized Delta serving table (`reservation_risk_serving`), provisions the native write-back table via `psycopg2`, and triggers the synced-table SNAPSHOT refresh. A synced table (reverse ETL) mirrors the Delta serving table into Postgres read-only; a Database Catalog registers the Postgres DB as a UC catalog for verification. Deploy is two-phase because the synced table reads its source schema at creation.

**Tech Stack:** Databricks Asset Bundles, Databricks CLI v0.298.0, Lakebase (managed Postgres / `database_instances`, `synced_database_tables`, `database_catalogs`), serverless notebook jobs, `databricks-sdk`, `psycopg2-binary`, Spark/Delta.

## Global Constraints

- Bundle name: `hotel_booking_ingest`. Resource files live in `resources/*.yml` (auto-included).
- Target/profile for all deploys and runs: `-t dev -p fevm-fe-bar-ecastillo`.
- Dev target vars: `catalog = fe_bar_ecastillo_catalog`, `schema = hotel_booking_dev`.
- Deploy/run/mutation shell commands require `required_permissions=["all"]` and can block for minutes; use a long block window.
- Notebooks are Databricks notebooks (`# Databricks notebook source`), serverless environment `client: "3"`. Each notebook ends with `dbutils.notebook.exit(json.dumps({...}))` (matches the governance/ML slices). There is no pytest harness; verification is `bundle validate`, job runs, and SQL/psql assertions.
- Logical Postgres DB name: `hotel`. Write-back table: `public.reservation_action`. Synced table UC name: `${catalog}.${schema}.reservation_risk_serving_synced`. UC catalog for the PG DB: `hotel_lakebase_pg`.
- Reference the deployed instance name via `${resources.database_instances.hotel_lakebase.name}` everywhere it is consumed (dev mode may prefix the literal name).
- `reservation_id` may be non-unique in `reservation_risk` (content-hash key; exact-duplicate bookings share an id). The serving table MUST be deduped on `reservation_id` so the synced-table primary key is valid.

---

### Task 1: `build_serving_table.py` notebook

**Files:**
- Create: `src/hotel_booking_lakebase/build_serving_table.py`

**Interfaces:**
- Consumes: Delta tables `${catalog}.${schema}.reservation_risk` (cols: `reservation_id, hotel, cancel_probability, risk_band, model_version, scored_at`) and `${catalog}.${schema}.silver_bookings` (cols include `reservation_id, arrival_date, lead_time, adr, market_segment, adults, children, babies, deposit_type, customer_type`).
- Produces: Delta table `${catalog}.${schema}.reservation_risk_serving` with columns `reservation_id, hotel, arrival_date, lead_time, adr, market_segment, adults, children, babies, deposit_type, customer_type, cancel_probability, risk_band, model_version, scored_at`; one row per distinct `reservation_id`. Notebook exit JSON `{"target": str, "rows": int}`.

- [ ] **Step 1: Write the notebook**

Create `src/hotel_booking_lakebase/build_serving_table.py`:

```python
# Databricks notebook source
# MAGIC %md
# MAGIC # Build `reservation_risk_serving` (denormalized Delta serving source)
# MAGIC
# MAGIC Joins `reservation_risk` (scores) with selected `silver_bookings` detail into one
# MAGIC row per reservation. This Delta table is the source the Lakebase synced table mirrors
# MAGIC into Postgres. Deduped on `reservation_id` so the synced-table primary key is valid
# MAGIC (the content-hash key is shared by exact-duplicate bookings by design).

# COMMAND ----------

dbutils.widgets.text("catalog", "", "Unity Catalog catalog")
dbutils.widgets.text("schema", "", "Schema holding reservation_risk / silver_bookings")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
assert CATALOG and SCHEMA, "catalog and schema parameters are required"

TARGET = f"{CATALOG}.{SCHEMA}.reservation_risk_serving"

# COMMAND ----------

from pyspark.sql import functions as F

risk = spark.table(f"{CATALOG}.{SCHEMA}.reservation_risk")
book = spark.table(f"{CATALOG}.{SCHEMA}.silver_bookings").select(
    "reservation_id",
    "arrival_date",
    "lead_time",
    "adr",
    "market_segment",
    "adults",
    "children",
    "babies",
    "deposit_type",
    "customer_type",
)

serving = (
    risk.alias("r")
    .join(book.alias("b"), on="reservation_id", how="left")
    .select(
        F.col("reservation_id"),
        F.col("r.hotel").alias("hotel"),
        F.col("b.arrival_date").alias("arrival_date"),
        F.col("b.lead_time").alias("lead_time"),
        F.col("b.adr").alias("adr"),
        F.col("b.market_segment").alias("market_segment"),
        F.col("b.adults").alias("adults"),
        F.col("b.children").alias("children"),
        F.col("b.babies").alias("babies"),
        F.col("b.deposit_type").alias("deposit_type"),
        F.col("b.customer_type").alias("customer_type"),
        F.col("r.cancel_probability").alias("cancel_probability"),
        F.col("r.risk_band").alias("risk_band"),
        F.col("r.model_version").alias("model_version"),
        F.col("r.scored_at").alias("scored_at"),
    )
    .dropDuplicates(["reservation_id"])
)

(
    serving.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(TARGET)
)

spark.sql(
    f"ALTER TABLE {TARGET} ALTER COLUMN reservation_id SET NOT NULL"
)
spark.sql(
    f"COMMENT ON TABLE {TARGET} IS "
    "'Denormalized per-reservation risk + booking detail. Source for the Lakebase synced "
    "table reservation_risk_serving_synced.'"
)

# COMMAND ----------

rows = spark.table(TARGET).count()
print(f"{TARGET}: {rows:,} rows")

dbutils.notebook.exit(__import__("json").dumps({"target": TARGET, "rows": rows}))
```

- [ ] **Step 2: Syntax-check the notebook locally**

Run: `python3 -c "import ast; ast.parse(open('src/hotel_booking_lakebase/build_serving_table.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/hotel_booking_lakebase/build_serving_table.py
git commit -m "Add Lakebase build_serving_table notebook"
```

---

### Task 2: `provision_writeback.py` notebook

**Files:**
- Create: `src/hotel_booking_lakebase/provision_writeback.py`

**Interfaces:**
- Consumes: base parameters `instance_name` (deployed Database Instance name) and `database` (`hotel`).
- Produces: Postgres logical DB `hotel` (created if missing) and table `public.reservation_action` (`id BIGSERIAL PK, reservation_id TEXT NOT NULL, action_type TEXT NOT NULL CHECK(...), note TEXT, acted_by TEXT, acted_at TIMESTAMPTZ DEFAULT now()`). Authoritative creator of the `hotel` database. Notebook exit JSON `{"database": str, "writeback_ready": true}`.

- [ ] **Step 1: Write the notebook**

Create `src/hotel_booking_lakebase/provision_writeback.py`:

```python
# Databricks notebook source
# MAGIC %md
# MAGIC # Provision Lakebase write-back schema
# MAGIC
# MAGIC Creates the `hotel` logical database (authoritative creator) and the append-only
# MAGIC `reservation_action` table the app writes to. Idempotent: safe to re-run every job run.

# COMMAND ----------

dbutils.widgets.text("instance_name", "", "Lakebase Database Instance name")
dbutils.widgets.text("database", "hotel", "Logical Postgres database")

INSTANCE = dbutils.widgets.get("instance_name").strip()
DATABASE = dbutils.widgets.get("database").strip()
assert INSTANCE and DATABASE, "instance_name and database parameters are required"

# COMMAND ----------

import uuid
import psycopg2
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
inst = w.database.get_database_instance(name=INSTANCE)
host = inst.read_write_dns
cred = w.database.generate_database_credential(
    request_id=str(uuid.uuid4()), instance_names=[INSTANCE]
)
token = cred.token
user = w.current_user.me().user_name
print(f"host={host} user={user}")

# COMMAND ----------

# Create the logical database if missing (CREATE DATABASE cannot run in a txn).
conn = psycopg2.connect(
    host=host, port=5432, dbname="databricks_postgres",
    user=user, password=token, sslmode="require",
)
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,))
if cur.fetchone() is None:
    cur.execute(f'CREATE DATABASE "{DATABASE}"')
    print(f"created database {DATABASE}")
else:
    print(f"database {DATABASE} already exists")
cur.close()
conn.close()

# COMMAND ----------

# Create the append-only write-back table in the hotel database.
conn = psycopg2.connect(
    host=host, port=5432, dbname=DATABASE,
    user=user, password=token, sslmode="require",
)
conn.autocommit = True
cur = conn.cursor()
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS public.reservation_action (
        id             BIGSERIAL PRIMARY KEY,
        reservation_id TEXT NOT NULL,
        action_type    TEXT NOT NULL
                       CHECK (action_type IN
                         ('reconfirmed','deposit_requested','overbooked_backup',
                          'released','note')),
        note           TEXT,
        acted_by       TEXT,
        acted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
)
cur.execute(
    "CREATE INDEX IF NOT EXISTS ix_reservation_action_res "
    "ON public.reservation_action (reservation_id, acted_at DESC);"
)
cur.close()
conn.close()

dbutils.notebook.exit(
    __import__("json").dumps({"database": DATABASE, "writeback_ready": True})
)
```

Note: the default DB on a Lakebase instance is `databricks_postgres`; we connect there first to issue `CREATE DATABASE`.

- [ ] **Step 2: Syntax-check the notebook locally**

Run: `python3 -c "import ast; ast.parse(open('src/hotel_booking_lakebase/provision_writeback.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/hotel_booking_lakebase/provision_writeback.py
git commit -m "Add Lakebase provision_writeback notebook"
```

---

### Task 3: `refresh_sync.py` notebook

**Files:**
- Create: `src/hotel_booking_lakebase/refresh_sync.py`

**Interfaces:**
- Consumes: base parameter `synced_table_name` (UC name of the synced table, `${catalog}.${schema}.reservation_risk_serving_synced`).
- Produces: triggers a full SNAPSHOT refresh of the synced table's underlying pipeline and polls to a terminal state. On first run (synced table not yet deployed) it skips gracefully. Notebook exit JSON `{"synced_table": str, "sync_state": str}` where `sync_state` is one of `SKIPPED_NOT_FOUND`, `COMPLETED`, or the terminal pipeline state.

- [ ] **Step 1: Write the notebook**

Create `src/hotel_booking_lakebase/refresh_sync.py`:

```python
# Databricks notebook source
# MAGIC %md
# MAGIC # Refresh the Lakebase synced table (SNAPSHOT)
# MAGIC
# MAGIC Triggers a full refresh of the synced table's underlying pipeline so Postgres reflects
# MAGIC the latest `reservation_risk_serving`. On the first job run the synced table is not
# MAGIC deployed yet (two-phase deploy), so this task skips gracefully.

# COMMAND ----------

dbutils.widgets.text("synced_table_name", "", "UC name of the synced table")
SYNCED = dbutils.widgets.get("synced_table_name").strip()
assert SYNCED, "synced_table_name parameter is required"

# COMMAND ----------

import json
import time
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound

w = WorkspaceClient()

try:
    st = w.database.get_synced_database_table(name=SYNCED)
except NotFound:
    print(f"synced table {SYNCED} not found - skipping (first-run / not deployed yet)")
    dbutils.notebook.exit(
        json.dumps({"synced_table": SYNCED, "sync_state": "SKIPPED_NOT_FOUND"})
    )

pipeline_id = st.data_synchronization_status.pipeline_id
print(f"synced table pipeline_id={pipeline_id}")

# COMMAND ----------

upd = w.pipelines.start_update(pipeline_id=pipeline_id, full_refresh=True)
update_id = upd.update_id
print(f"started update {update_id}")

TERMINAL = {"COMPLETED", "FAILED", "CANCELED"}
state = None
for _ in range(120):  # up to ~20 min
    u = w.pipelines.get_update(pipeline_id=pipeline_id, update_id=update_id).update
    state = str(u.state)
    if any(t in state for t in TERMINAL):
        break
    time.sleep(10)

print(f"final update state: {state}")
if "COMPLETED" not in (state or ""):
    raise RuntimeError(f"synced table refresh did not complete: {state}")

dbutils.notebook.exit(
    json.dumps({"synced_table": SYNCED, "sync_state": state})
)
```

Note: `data_synchronization_status.pipeline_id` and `pipelines.get_update(...).update.state` are the expected SDK shapes; if a field name differs at runtime, adjust to the actual attribute (surface it from the run output) — the control flow (get → start_update → poll) is what matters.

- [ ] **Step 2: Syntax-check the notebook locally**

Run: `python3 -c "import ast; ast.parse(open('src/hotel_booking_lakebase/refresh_sync.py').read()); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/hotel_booking_lakebase/refresh_sync.py
git commit -m "Add Lakebase refresh_sync notebook"
```

---

### Task 4: Database Instance + `hotel_lakebase_sync` job resource

**Files:**
- Create: `resources/hotel_lakebase.yml`

**Interfaces:**
- Consumes: the three notebooks from Tasks 1-3; bundle vars `catalog`, `schema`.
- Produces: bundle resources `database_instances.hotel_lakebase` and `jobs.hotel_lakebase_sync` (tasks `build_serving` → `provision_writeback`, `build_serving` → `refresh_sync`). `refresh_sync` receives `synced_table_name`; `provision_writeback` receives `instance_name = ${resources.database_instances.hotel_lakebase.name}` and `database = hotel`.

- [ ] **Step 1: Write the resource file**

Create `resources/hotel_lakebase.yml`:

```yaml
resources:
  database_instances:
    hotel_lakebase:
      name: hotel-lakebase
      capacity: CU_1

  jobs:
    hotel_lakebase_sync:
      name: hotel_lakebase_sync
      description: >-
        Refresh the Lakebase serving layer: build reservation_risk_serving (Delta),
        provision the reservation_action write-back table, and refresh the synced-table
        SNAPSHOT. Run: `databricks bundle run hotel_lakebase_sync -t dev`.
      tasks:
        - task_key: build_serving
          notebook_task:
            notebook_path: ../src/hotel_booking_lakebase/build_serving_table.py
            base_parameters:
              catalog: ${var.catalog}
              schema: ${var.schema}
          environment_key: default

        - task_key: provision_writeback
          depends_on:
            - task_key: build_serving
          notebook_task:
            notebook_path: ../src/hotel_booking_lakebase/provision_writeback.py
            base_parameters:
              instance_name: ${resources.database_instances.hotel_lakebase.name}
              database: hotel
          environment_key: default

        - task_key: refresh_sync
          depends_on:
            - task_key: build_serving
          notebook_task:
            notebook_path: ../src/hotel_booking_lakebase/refresh_sync.py
            base_parameters:
              synced_table_name: ${var.catalog}.${var.schema}.reservation_risk_serving_synced
          environment_key: default

      environments:
        - environment_key: default
          spec:
            client: "3"
            dependencies:
              - psycopg2-binary
              - databricks-sdk
```

- [ ] **Step 2: Validate the bundle**

Run: `databricks bundle validate -t dev -p fevm-fe-bar-ecastillo`
Expected: `Validation OK!` (no errors). If a warning about `${resources.database_instances.hotel_lakebase.name}` resolution appears, confirm the reference resolves in the validate output's summary; if it does not resolve, replace with the literal `hotel-lakebase` and note it.

- [ ] **Step 3: Commit**

```bash
git add resources/hotel_lakebase.yml
git commit -m "Add Lakebase database instance + hotel_lakebase_sync job"
```

---

### Task 5: Synced Table + Database Catalog resource (held out for phase 1)

**Files:**
- Create: `resources/hotel_lakebase_synced.yml`

**Interfaces:**
- Consumes: `database_instances.hotel_lakebase`; Delta table `${catalog}.${schema}.reservation_risk_serving` (must exist before this deploys).
- Produces: `synced_database_tables.reservation_risk_serving_synced` (SNAPSHOT, PK `reservation_id`, logical DB `hotel`) and `database_catalogs.hotel_lakebase_pg` (registers PG DB `hotel` as UC catalog).

- [ ] **Step 1: Write the resource file**

Create `resources/hotel_lakebase_synced.yml`:

```yaml
resources:
  synced_database_tables:
    reservation_risk_serving_synced:
      name: ${var.catalog}.${var.schema}.reservation_risk_serving_synced
      database_instance_name: ${resources.database_instances.hotel_lakebase.name}
      logical_database_name: hotel
      spec:
        source_table_full_name: ${var.catalog}.${var.schema}.reservation_risk_serving
        primary_key_columns:
          - reservation_id
        scheduling_policy: SNAPSHOT
        create_database_objects_if_missing: true
        new_pipeline_spec:
          storage_catalog: ${var.catalog}
          storage_schema: ${var.schema}

  database_catalogs:
    hotel_lakebase_pg:
      name: hotel_lakebase_pg
      database_instance_name: ${resources.database_instances.hotel_lakebase.name}
      database_name: hotel
      create_database_if_not_exists: true
```

- [ ] **Step 2: Validate with the file present**

Run: `databricks bundle validate -t dev -p fevm-fe-bar-ecastillo`
Expected: `Validation OK!`

- [ ] **Step 3: Move the file aside for the phase-1 deploy**

Run: `mv resources/hotel_lakebase_synced.yml /tmp/hotel_lakebase_synced.yml && databricks bundle validate -t dev -p fevm-fe-bar-ecastillo`
Expected: `Validation OK!` (synced/catalog resources now absent)

- [ ] **Step 4: Commit (file is tracked; it will be restored in Task 7)**

```bash
git add resources/hotel_lakebase_synced.yml
git commit -m "Add Lakebase synced table + UC catalog resource"
```

Note: the `git add` records the file from your working tree. Since it was moved to `/tmp`, first restore it for the commit, then move it aside again:

```bash
cp /tmp/hotel_lakebase_synced.yml resources/hotel_lakebase_synced.yml
git add resources/hotel_lakebase_synced.yml
git commit -m "Add Lakebase synced table + UC catalog resource"
mv resources/hotel_lakebase_synced.yml /tmp/hotel_lakebase_synced.yml
```

---

### Task 6: Phase-1 deploy + run (instance, serving Delta, write-back)

**Files:** none (deploy/run/verify only). Precondition: `resources/hotel_lakebase_synced.yml` is at `/tmp` (not in `resources/`).

**Interfaces:**
- Consumes: Tasks 4-5 resources; existing `reservation_risk` + `silver_bookings`.
- Produces: deployed Database Instance; `reservation_risk_serving` Delta table; `hotel` PG DB + `reservation_action` table.

- [ ] **Step 1: Deploy (instance + job only)**

Run: `databricks bundle deploy -t dev -p fevm-fe-bar-ecastillo` (required_permissions=["all"], long block)
Expected: `Deployment complete!`

- [ ] **Step 2: Confirm the instance becomes AVAILABLE**

Run: `databricks database list-database-instances -p fevm-fe-bar-ecastillo -o json | python3 -c "import sys,json;[print(i['name'],i.get('state')) for i in json.load(sys.stdin)]"`
Expected: the `hotel-lakebase` instance (possibly dev-prefixed) listed; state reaches `AVAILABLE` (re-run until it does; provisioning takes a few minutes).

- [ ] **Step 3: Run the job**

Run: `databricks bundle run hotel_lakebase_sync -t dev -p fevm-fe-bar-ecastillo` (required_permissions=["all"], long block)
Expected: `TERMINATED SUCCESS`. Task outputs: `build_serving` → `{"target": "...reservation_risk_serving", "rows": N}`; `provision_writeback` → `{"database": "hotel", "writeback_ready": true}`; `refresh_sync` → `{"sync_state": "SKIPPED_NOT_FOUND"}`.

- [ ] **Step 4: Verify the serving Delta table (dedup correct)**

Run:
```bash
databricks api post /api/2.0/sql/statements -p fevm-fe-bar-ecastillo --json '{
  "warehouse_id": "94dfd610249e30f5",
  "statement": "SELECT (SELECT count(*) FROM fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk_serving) AS serving_rows, (SELECT count(DISTINCT reservation_id) FROM fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk) AS distinct_risk_ids"
}'
```
Expected: `serving_rows == distinct_risk_ids` (both a bit ≤ 119,389).

- [ ] **Step 5: Commit an evidence stub (optional checkpoint)**

No file change yet — proceed to Task 7. (Evidence doc is written in Task 8.)

---

### Task 7: Phase-2 deploy (synced table + catalog) + verify serving

**Files:** restores `resources/hotel_lakebase_synced.yml` from `/tmp`.

**Interfaces:**
- Consumes: `reservation_risk_serving` Delta table (from Task 6).
- Produces: deployed synced table (Postgres read replica) + UC catalog `hotel_lakebase_pg`; verified end-to-end read + write-back.

- [ ] **Step 1: Restore the held resource and deploy**

Run:
```bash
mv /tmp/hotel_lakebase_synced.yml resources/hotel_lakebase_synced.yml
databricks bundle deploy -t dev -p fevm-fe-bar-ecastillo
```
(required_permissions=["all"], long block) Expected: `Deployment complete!`

- [ ] **Step 2: Confirm the synced table comes ONLINE**

Run: `databricks database get-synced-database-table fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk_serving_synced -p fevm-fe-bar-ecastillo -o json | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('data_synchronization_status'))"`
Expected: a status object; detailed state reaches an online/synced state (re-run until synced).

- [ ] **Step 3: Re-run the job so `refresh_sync` performs a real refresh**

Run: `databricks bundle run hotel_lakebase_sync -t dev -p fevm-fe-bar-ecastillo` (required_permissions=["all"], long block)
Expected: `TERMINATED SUCCESS`; `refresh_sync` → `{"sync_state": "...COMPLETED..."}`.

- [ ] **Step 4: Verify the Postgres row count via the UC catalog**

Run:
```bash
databricks api post /api/2.0/sql/statements -p fevm-fe-bar-ecastillo --json '{
  "warehouse_id": "94dfd610249e30f5",
  "statement": "SELECT count(*) AS pg_rows FROM hotel_lakebase_pg.public.reservation_risk_serving_synced"
}'
```
Expected: `pg_rows` equals `serving_rows` from Task 6 Step 4. (If the UC catalog name was dev-prefixed, use the actual name from `databricks catalogs list`.)

- [ ] **Step 5: Simulate an app write-back and read it back**

Run:
```bash
databricks api post /api/2.0/sql/statements -p fevm-fe-bar-ecastillo --json '{
  "warehouse_id": "94dfd610249e30f5",
  "statement": "INSERT INTO hotel_lakebase_pg.public.reservation_action (reservation_id, action_type, note, acted_by) SELECT reservation_id, '\''reconfirmed'\'', '\''demo write-back'\'', '\''plan-verify'\'' FROM hotel_lakebase_pg.public.reservation_risk_serving_synced LIMIT 1"
}'
databricks api post /api/2.0/sql/statements -p fevm-fe-bar-ecastillo --json '{
  "warehouse_id": "94dfd610249e30f5",
  "statement": "SELECT reservation_id, action_type, acted_by, acted_at FROM hotel_lakebase_pg.public.reservation_action ORDER BY acted_at DESC LIMIT 5"
}'
```
Expected: the insert succeeds and the row is returned (proves the native write-back table is writable/readable through the UC catalog). If UC-catalog writes to Lakebase are not permitted, fall back to a psql insert against the instance host and note it.

- [ ] **Step 6: Commit**

```bash
git add resources/hotel_lakebase_synced.yml
git commit -m "Deploy Lakebase synced table + UC catalog (phase 2)"
```

---

### Task 8: Docs — README + evidence

**Files:**
- Modify: `README.md`
- Create: `docs/evidence/lakebase-serving-run.md`

**Interfaces:**
- Consumes: verified results from Tasks 6-7.
- Produces: a Lakebase run block in the README and an evidence doc capturing the two-phase deploy, row counts, and the write-back check.

- [ ] **Step 1: Add a Lakebase section to `README.md`**

Add (near the ML/serving sections) a fenced block:

```markdown
### Lakebase serving + write-back

```bash
# Phase 1 (first time): synced table held out, then deploy + run
databricks bundle deploy -t dev
databricks bundle run hotel_lakebase_sync -t dev   # build serving + provision write-back
# Phase 2: add resources/hotel_lakebase_synced.yml, deploy, re-run to refresh the SNAPSHOT
databricks bundle deploy -t dev
databricks bundle run hotel_lakebase_sync -t dev
```

Serves `reservation_risk_serving` from Postgres (`hotel.public.reservation_risk_serving_synced`,
read-only) and exposes an append-only `reservation_action` write-back table. See the design
spec `docs/superpowers/specs/2026-09-29-lakebase-serving-writeback-design.md`.
```

- [ ] **Step 2: Write the evidence doc**

Create `docs/evidence/lakebase-serving-run.md` capturing: the two-phase deploy sequence, the instance name/state, `build_serving` rows, `provision_writeback` result, both `refresh_sync` outcomes (SKIPPED then COMPLETED), the Postgres row-count match, and the write-back insert/read result. Use the real numbers from the runs (do not leave placeholders). Follow the format of `docs/evidence/ml-cancel-classifier-run.md`.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/evidence/lakebase-serving-run.md
git commit -m "Document Lakebase serving + write-back slice"
```

- [ ] **Step 4: Push**

```bash
git push origin main
```
Expected: fast-forward push succeeds (active gh account `jestebanc16`).

---

## Self-Review

**Spec coverage:**
- Read-serving + write-back → Tasks 1 (serving Delta), 5/7 (synced read replica), 2 (write-back table). ✓
- Denormalized serving table → Task 1. ✓
- SNAPSHOT synced table → Task 5 (`scheduling_policy: SNAPSHOT`), Task 3/7 (refresh). ✓
- All in the bundle → Tasks 4-5 resources; Tasks 6-7 deploy. ✓
- Append-only `reservation_action` (exact columns) → Task 2. ✓
- Two-phase deploy (chicken-and-egg) → Tasks 5 (hold out), 6 (phase 1), 7 (phase 2). ✓
- `refresh_sync` first-run tolerance → Task 3 (`SKIPPED_NOT_FOUND`), verified Task 6 Step 3. ✓
- `provision_writeback` authoritative DB creator → Task 2. ✓
- UC catalog registration → Task 5 (`database_catalogs`), verified Task 7 Steps 4-5. ✓
- Verification (row-count match, sample write-back) → Tasks 6-7. ✓
- Cost note (`CU_1`, `stopped` when idle) → covered in spec; evidence Task 8. ✓

**Placeholder scan:** No TBD/TODO; every code/command step contains full content. Task 8 Step 2 describes the evidence doc contents (a prose doc, not code) and explicitly forbids placeholders. ✓

**Type/name consistency:** `reservation_risk_serving` (Delta), `reservation_risk_serving_synced` (synced UC/PG), `reservation_action`, `hotel` DB, `hotel_lakebase` instance / `hotel-lakebase` name, `hotel_lakebase_pg` catalog, warehouse `94dfd610249e30f5`, profile `fevm-fe-bar-ecastillo` — used consistently across tasks. Notebook exit JSON keys match the interfaces. ✓

**Known runtime risks (flagged, not blocking):** dev-mode prefixing of the instance/catalog names (mitigated via `${resources...name}` reference and "use actual name" verification notes); exact SDK attribute names in `refresh_sync` (control flow is what matters; adjust attribute if runtime differs); whether UC-catalog writes to Lakebase are permitted (psql fallback noted in Task 7 Step 5).
