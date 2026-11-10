# Databricks notebook source
# MAGIC %md
# MAGIC # Provision Lakebase write-back schema + app Postgres grants
# MAGIC
# MAGIC Creates the `hotel` logical database (authoritative creator) and the append-only
# MAGIC `reservation_action` table the app writes to. Then grants the Databricks App
# MAGIC service principal (looked up by `app_name`) USAGE/SELECT on the synced serving
# MAGIC schema/table and SELECT/INSERT on the write-back table.
# MAGIC
# MAGIC Idempotent: safe to re-run every job run. Grants are a no-op skip (not a failure)
# MAGIC when the app or its Postgres role is not provisioned yet — start the app once so
# MAGIC Databricks creates the role, then re-run this job.

# COMMAND ----------

dbutils.widgets.text("instance_name", "", "Lakebase Database Instance name")
dbutils.widgets.text("database", "hotel", "Logical Postgres database")
dbutils.widgets.text("serving_schema", "", "Postgres schema for the synced serving table")
dbutils.widgets.text("app_name", "", "Databricks App name whose SP needs grants")
dbutils.widgets.text("serving_table", "reservation_risk_serving_synced", "Synced table name")

INSTANCE = dbutils.widgets.get("instance_name").strip()
DATABASE = dbutils.widgets.get("database").strip()
SERVING_SCHEMA = dbutils.widgets.get("serving_schema").strip()
APP_NAME = dbutils.widgets.get("app_name").strip()
SERVING_TABLE = dbutils.widgets.get("serving_table").strip() or "reservation_risk_serving_synced"
assert INSTANCE and DATABASE, "instance_name and database parameters are required"

# COMMAND ----------

import json
import uuid
from typing import Optional

import psycopg2
from psycopg2 import sql
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
with psycopg2.connect(
    host=host, port=5432, dbname="databricks_postgres",
    user=user, password=token, sslmode="require",
) as conn:
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,))
        if cur.fetchone() is None:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
            print(f"created database {DATABASE}")
        else:
            print(f"database {DATABASE} already exists")

# COMMAND ----------

# Create the append-only write-back table in the hotel database.
with psycopg2.connect(
    host=host, port=5432, dbname=DATABASE,
    user=user, password=token, sslmode="require",
) as conn:
    conn.autocommit = True
    with conn.cursor() as cur:
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

# COMMAND ----------

def _resolve_app_sp(app_name: str) -> Optional[str]:
    """Return the app service-principal client id, or None if the app is missing."""
    if not app_name:
        print("skip grants: app_name not set")
        return None
    try:
        app = w.apps.get(name=app_name)
    except Exception as exc:  # SDK error types vary by version; treat missing as skip
        msg = str(exc).lower()
        if "404" in msg or "not found" in msg or "does not exist" in msg:
            print(f"skip grants: app {app_name!r} not found ({exc})")
            return None
        raise
    sp = getattr(app, "service_principal_client_id", None)
    if not sp:
        print(f"skip grants: app {app_name!r} has no service_principal_client_id yet")
        return None
    print(f"app={app_name} service_principal_client_id={sp}")
    return sp


def _grant_app_privileges(cur, sp: str, serving_schema: str, serving_table: str) -> dict:
    """Idempotent GRANTs for the app SP. Skips (no raise) if role/schema/table missing."""
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (sp,))
    if cur.fetchone() is None:
        print(
            f"skip grants: Postgres role {sp!r} not found yet. "
            "Start the app once so Databricks provisions the role, then re-run."
        )
        return {"grants_applied": False, "reason": "role_missing"}

    if not serving_schema:
        print("skip grants: serving_schema not set")
        return {"grants_applied": False, "reason": "schema_missing"}

    cur.execute(
        "SELECT 1 FROM pg_namespace WHERE nspname = %s", (serving_schema,)
    )
    if cur.fetchone() is None:
        print(
            f"skip grants: schema {serving_schema!r} not found yet "
            "(synced table may not be deployed). Re-run after sync is online."
        )
        return {"grants_applied": False, "reason": "schema_missing"}

    cur.execute(
        """
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s
        """,
        (serving_schema, serving_table),
    )
    if cur.fetchone() is None:
        print(
            f"skip grants: table {serving_schema}.{serving_table} not found yet. "
            "Re-run after the synced table is online."
        )
        return {"grants_applied": False, "reason": "table_missing"}

    role = sql.Identifier(sp)
    schema = sql.Identifier(serving_schema)
    table = sql.SQL("{}.{}").format(schema, sql.Identifier(serving_table))

    cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, role))
    cur.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(table, role))
    cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
    cur.execute(
        sql.SQL("GRANT SELECT, INSERT ON public.reservation_action TO {}").format(role)
    )
    cur.execute(
        sql.SQL(
            "GRANT USAGE, SELECT ON SEQUENCE public.reservation_action_id_seq TO {}"
        ).format(role)
    )
    print(
        f"granted USAGE/SELECT on {serving_schema}.{serving_table} and "
        f"SELECT/INSERT on public.reservation_action to {sp}"
    )
    return {
        "grants_applied": True,
        "sp": sp,
        "serving_schema": serving_schema,
        "serving_table": serving_table,
    }


grant_result = {"grants_applied": False, "reason": "not_attempted"}
sp = _resolve_app_sp(APP_NAME)
if sp:
    with psycopg2.connect(
        host=host, port=5432, dbname=DATABASE,
        user=user, password=token, sslmode="require",
    ) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            grant_result = _grant_app_privileges(
                cur, sp, SERVING_SCHEMA, SERVING_TABLE
            )

# COMMAND ----------

dbutils.notebook.exit(
    json.dumps(
        {
            "database": DATABASE,
            "writeback_ready": True,
            **grant_result,
        }
    )
)
