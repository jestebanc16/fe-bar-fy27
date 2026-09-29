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
