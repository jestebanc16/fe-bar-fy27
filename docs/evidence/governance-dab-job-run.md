# Evidence: governance re-run via the DAB job

The `hotel_booking_governance` bundle job re-applies the Unity Catalog governance layer
on serverless (no SQL warehouse). This captures a dev run.

## Command

```bash
databricks bundle deploy -t dev -p serverless_stable_eojwo0
databricks bundle run   hotel_booking_governance -t dev -p serverless_stable_eojwo0
```

## Result

```
"[dev esteban_castillo] hotel_booking_governance" TERMINATED SUCCESS
```

Structured summary returned by the notebook (`dbutils.notebook.exit`):

```json
{
  "catalog": "serverless_stable_eojwo0_catalog",
  "schema": "hotel_booking_dev",
  "member_fn": "is_member",
  "ok": 38,
  "fail": 36,
  "per_file": {
    "functions.sql": {"ok": 2,  "fail": 0},
    "comments.sql":  {"ok": 20, "fail": 11},
    "tags.sql":      {"ok": 8,  "fail": 0},
    "policies.sql":  {"ok": 8,  "fail": 0},
    "grants.sql":    {"ok": 0,  "fail": 25}
  }
}
```

## Reading the result

- The job dropped the SQL-warehouse dependency: the serverless notebook runs every
  statement via `spark.sql`. It resolved the membership function to `is_member`
  (workspace groups), matching `governance/apply.sh` in this workspace.
- Enforcement layer applied cleanly:
  - `functions.sql` 2/2 — `mask_pii` + `hotel_row_filter` UDFs (re)created.
  - `policies.sql` 8/8 — column masks (country/agent/company) + per-property row filter on
    `silver_bookings` re-applied.
  - `tags.sql` 8/8 — `layer` / `certified` table tags + `hb_data_class` column tags.
  - `comments.sql` 20 OK — the full silver data dictionary + table-level comments.
- Expected failures (identical to `apply.sh`; documented limitations, not regressions):
  - `comments.sql` 11 FAIL — `EXPECT_TABLE_NOT_VIEW`: `gold_hotel_month` is a materialized
    view and rejects `ALTER TABLE ... ALTER COLUMN` for per-column comments. Gold carries
    table-level comments/tags instead.
  - `grants.sql` 25 FAIL — `PRINCIPAL_DOES_NOT_EXIST`: UC object GRANTs require
    account-level group principals, unavailable in this workspace-groups-only environment.
    The mask + row-filter enforcement (keyed to the same groups via `is_member`) does not
    depend on the grants.

## Idempotency

The job is safe to re-run: UDFs use `CREATE OR REPLACE`, policies `DROP` before `SET`,
and tags/comments are declarative. Re-running produces the same 38 OK / 36 FAIL summary.

Structural proof of the applied masks / filters / tags / comments / lineage (via
`information_schema` and `system.access.table_lineage`) is in
[unity-catalog-governance.md](unity-catalog-governance.md).
