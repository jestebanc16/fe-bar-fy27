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
