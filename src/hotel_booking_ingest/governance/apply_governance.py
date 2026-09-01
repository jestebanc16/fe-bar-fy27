# Databricks notebook source
# MAGIC %md
# MAGIC # Apply Unity Catalog governance
# MAGIC
# MAGIC Re-runnable, serverless port of `governance/apply.sh`. Packaged as a Databricks
# MAGIC Asset Bundle job (`hotel_booking_governance`) so re-applying governance is just
# MAGIC `databricks bundle run hotel_booking_governance -t <target>`.
# MAGIC
# MAGIC What it does (idempotent):
# MAGIC 1. Creates the four persona groups and adds the run-as user to `hotel_engineer`.
# MAGIC 2. Probes which membership function resolves (`is_account_group_member` vs `is_member`).
# MAGIC 3. Reads the bundled `governance/*.sql`, substitutes `{catalog}` / `{schema}` /
# MAGIC    `{member_fn}`, and runs each statement via `spark.sql` (continue-on-error + summary).
# MAGIC
# MAGIC `constraints.sql` is reference-only (SDP streaming tables / materialized views reject
# MAGIC external constraint DDL) and is intentionally skipped. `grants.sql` requires
# MAGIC account-level group principals; those statements FAIL in a workspace-groups-only
# MAGIC environment (expected) while masks/filters/tags/comments apply cleanly.

# COMMAND ----------

dbutils.widgets.text("catalog", "", "Unity Catalog catalog")
dbutils.widgets.text("schema", "", "Schema for bronze/silver/gold + raw Volume")
dbutils.widgets.text(
    "governance_path", "", "Workspace path to the synced governance/ folder"
)

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
GOVERNANCE_PATH = dbutils.widgets.get("governance_path").strip().rstrip("/")

assert CATALOG, "catalog parameter is required"
assert SCHEMA, "schema parameter is required"
assert GOVERNANCE_PATH, "governance_path parameter is required"

# Persona groups. Column masks + row filters (policies.sql) do the per-persona
# restriction; grants (grants.sql) control which tables each persona can read at all.
PERSONAS = ["hotel_engineer", "hotel_analyst", "hotel_mgr_city", "hotel_mgr_resort"]

# Applied in dependency order: functions before the policies that reference them.
# constraints.sql is reference-only and deliberately excluded.
SQL_FILES = ["functions.sql", "comments.sql", "tags.sql", "policies.sql", "grants.sql"]

print(f"== Target: {CATALOG}.{SCHEMA} ==")
print(f"   governance_path: {GOVERNANCE_PATH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Persona groups (idempotent) + add run-as user to `hotel_engineer`

# COMMAND ----------

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()


def group_id(display_name: str):
    """Return the SCIM id for a group display name, or None if absent."""
    matches = list(w.groups.list(filter=f'displayName eq "{display_name}"'))
    return matches[0].id if matches else None


print("== Persona groups ==")
for g in PERSONAS:
    if group_id(g):
        print(f"  exists  {g}")
        continue
    try:
        w.groups.create(display_name=g)
        print(f"  created {g}")
    except Exception as e:  # noqa: BLE001 - report and continue
        # Benign if a concurrent run already created it.
        print(f"  create skipped {g}: {str(e)[:120]}")

# Add the run-as identity to hotel_engineer so the operator keeps unmasked, all-rows
# access. Raw SCIM PATCH (mirrors apply.sh) is the most robust across SDK versions.
me = w.current_user.me()
my_id = me.id
eng_id = group_id("hotel_engineer")
print(f"== Operator {me.user_name} (id {my_id}) -> hotel_engineer (id {eng_id}) ==")
if my_id and eng_id:
    try:
        w.api_client.do(
            "PATCH",
            f"/api/2.0/preview/scim/v2/Groups/{eng_id}",
            body={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [
                    {"op": "add", "path": "members", "value": [{"value": my_id}]}
                ],
            },
        )
        print("  membership ensured")
    except Exception as e:  # noqa: BLE001 - already-a-member is benign
        print(f"  patch skipped: {str(e)[:120]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Probe the working group-membership function

# COMMAND ----------

MEMBER_FN = "is_account_group_member"
try:
    probe = spark.sql("SELECT is_account_group_member('hotel_engineer') AS m").collect()[0][0]
except Exception as e:  # noqa: BLE001
    probe = None
    print(f"  probe error: {str(e)[:120]}")

if probe is True:
    print("== Using is_account_group_member ==")
else:
    print(f"== is_account_group_member did not resolve (got: {probe}); using is_member ==")
    MEMBER_FN = "is_member"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Apply each governance SQL file, statement by statement

# COMMAND ----------


def read_governance_file(name: str) -> str:
    """Read a bundled governance SQL file from the synced workspace folder."""
    with open(f"{GOVERNANCE_PATH}/{name}", "r") as fh:
        return fh.read()


def statements(sql_text: str):
    """Strip `--` comment lines, substitute placeholders, split on `;`."""
    lines = [l for l in sql_text.splitlines() if not l.lstrip().startswith("--")]
    text = (
        "\n".join(lines)
        .replace("{catalog}", CATALOG)
        .replace("{schema}", SCHEMA)
        .replace("{member_fn}", MEMBER_FN)
    )
    return [s.strip() for s in text.split(";") if s.strip()]


ok = 0
fail = 0
per_file = {}
failures = []
for name in SQL_FILES:
    f_ok = f_fail = 0
    print(f"\n== Applying {name} ==")
    for stmt in statements(read_governance_file(name)):
        label = " ".join(stmt.split())[:72]
        try:
            spark.sql(stmt)
            ok += 1
            f_ok += 1
            print(f"  OK   {label}")
        except Exception as e:  # noqa: BLE001 - continue-on-error, report summary
            fail += 1
            f_fail += 1
            msg = " ".join(str(e).split())[:150]
            failures.append({"file": name, "stmt": label, "error": msg})
            print(f"  FAIL {label}")
            print(f"       {msg}")
    per_file[name] = {"ok": f_ok, "fail": f_fail}

print(f"\n== Governance apply complete: {ok} OK, {fail} FAIL ==")
print(
    "   (constraints.sql is reference-only; grant FAILs are expected without account groups.)"
)

# COMMAND ----------

# MAGIC %md
# MAGIC Fail the task only if *everything* failed (e.g. bad catalog/schema or no table
# MAGIC access); expected per-statement grant failures without account groups do not fail
# MAGIC the run. Exit with a structured summary so the run output is machine-readable.

# COMMAND ----------

import json

if ok == 0 and fail > 0:
    raise RuntimeError(
        f"All {fail} governance statements failed - check catalog/schema, "
        "tables exist (run the ingest pipeline first), and permissions."
    )

dbutils.notebook.exit(
    json.dumps(
        {
            "catalog": CATALOG,
            "schema": SCHEMA,
            "member_fn": MEMBER_FN,
            "ok": ok,
            "fail": fail,
            "per_file": per_file,
            "failures": failures,
        }
    )
)
