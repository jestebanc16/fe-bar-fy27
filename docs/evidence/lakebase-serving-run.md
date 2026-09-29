# Evidence: Lakebase serving + write-back slice (dev)

Stood up a Lakebase (managed Postgres) serving layer on the
`fevm-fe-bar-ecastillo` workspace / `fe_bar_ecastillo_catalog.hotel_booking_dev` schema: a
denormalized Delta serving table synced read-only into Postgres, plus an append-only
`reservation_action` write-back table the app writes to. All deployed via the DAB bundle. Full
design: `docs/superpowers/specs/2026-09-29-lakebase-serving-writeback-design.md`.

## Resources

- **Database Instance** `hotel-lakebase` (`capacity CU_1`) — state `AVAILABLE`. Dev mode did
  not prefix the instance name. Hosts logical Postgres DB `hotel`.
- **Job** `hotel_lakebase_sync` — three serverless tasks `build_serving` -> `provision_writeback`,
  `build_serving` -> `refresh_sync`.
- **Synced table** `fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk_serving_synced`
  — SNAPSHOT, PK `reservation_id`, state `SYNCED_TABLE_ONLINE_NO_PENDING_UPDATE`, provisioning
  `ACTIVE`.

## Two-phase deploy

The synced table reads its source table's schema at creation, so the Delta source
(`reservation_risk_serving`) must exist first.

- **Phase 1** — deployed instance + job (synced table held out at `/tmp`). Ran
  `hotel_lakebase_sync`:
  - `build_serving` -> `{"target": "...reservation_risk_serving", "rows": 87395}`
  - `provision_writeback` -> `{"database": "hotel", "writeback_ready": true}`
  - `refresh_sync` -> `{"sync_state": "SKIPPED_NOT_FOUND"}` (synced table not deployed yet —
    graceful first-run skip)
- **Phase 2** — restored `resources/hotel_lakebase_synced.yml`, deployed the synced table
  (SNAPSHOT auto-populated on creation), re-ran `hotel_lakebase_sync`:
  - `build_serving` -> `{"rows": 87395}`
  - `provision_writeback` -> `{"writeback_ready": true}`
  - `refresh_sync` -> `{"sync_state": "UpdateInfoState.COMPLETED"}` (real refresh path)

## Dedup was required

`reservation_risk` has one row per scored `silver_bookings` row (119,389), but `reservation_id`
is a content hash and exact-duplicate bookings share it. `build_serving` dedups on
`reservation_id`, yielding **87,395** distinct rows. Verified via Databricks SQL:

```
SELECT count(*) FROM reservation_risk_serving,
       count(DISTINCT reservation_id) FROM reservation_risk
-> 87395, 87395   (equal)
```

## Read side (synced replica)

Queried the synced table by its UC name:

```
SELECT count(*), count(DISTINCT reservation_id),
       sum(CASE WHEN risk_band='high' THEN 1 ELSE 0 END)
FROM ...reservation_risk_serving_synced
-> 87395, 87395, 10238
```

Postgres row count matches the Delta source (87,395); 10,238 reservations in the high-risk band.

## Write-back (native Postgres table)

The synced table lands in Postgres schema `hotel_booking_dev` (the UC schema name carries over);
the write-back table is `public.reservation_action` — both in the `hotel` database, so the app
can join across them. Verified an app-style write-back via psql (OAuth token from
`databricks database generate-database-credential`):

```sql
INSERT INTO public.reservation_action (reservation_id, action_type, note, acted_by)
SELECT reservation_id, 'reconfirmed', 'demo write-back', 'plan-verify'
FROM hotel_booking_dev.reservation_risk_serving_synced WHERE risk_band='high' LIMIT 1;
-- INSERT 0 1
SELECT id, left(reservation_id,12), action_type, acted_by, acted_at
FROM public.reservation_action ORDER BY acted_at DESC LIMIT 5;
-- 1 | 200760d231d5 | reconfirmed | plan-verify | 2026-09-29 20:55:42.544708+00
```

The insert reads from the synced read table and writes to the native table in one statement —
proving the read + write-back tables are co-located and usable together.

## Deviations from the design (environment-driven)

1. **`databricks-sdk` version pin.** The first job run failed with
   `'WorkspaceClient' object has no attribute 'database'`: the serverless base image ships an
   older SDK and an unpinned `databricks-sdk` dependency is not upgraded. Fixed by pinning
   `databricks-sdk>=0.143.0` in the job environment (`resources/hotel_lakebase.yml`). The
   `w.database` method/field names used by the notebooks (`get_database_instance.read_write_dns`,
   `generate_database_credential.token`, `get_synced_database_table.data_synchronization_status.pipeline_id`,
   `pipelines.start_update(...).update_id`, `get_update(...).update.state`) were confirmed
   against SDK 0.143.0 and worked in production (`refresh_sync` returned `COMPLETED`).
2. **UC catalog registration dropped.** The design included a `database_catalogs.hotel_lakebase_pg`
   resource to expose the Postgres DB to Databricks SQL. Creating a UC catalog requires the
   metastore-level `CREATE CATALOG` privilege, which the run-as identity lacks on this FEVM
   workspace (workspace admin != metastore admin). Removed the resource so the bundle deploys
   cleanly (a commented, ready-to-enable block remains in
   `resources/hotel_lakebase_synced.yml`). Impact is minimal: the synced read table is already
   UC-queryable under the existing catalog/schema, and the native write-back table is accessed
   directly over Postgres — which is how the app will use it anyway.

## Cost note

`hotel-lakebase` is `CU_1` (smallest). Set the instance `stopped: true` when idle to avoid
compute charges; the SNAPSHOT synced table only consumes compute during a refresh run.
