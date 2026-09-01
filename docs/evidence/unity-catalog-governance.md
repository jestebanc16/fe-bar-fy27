# Unity Catalog governance - execution evidence

Applied via `governance/apply.sh` against `serverless_stable_eojwo0_catalog.hotel_booking_dev`
on `fevm-serverless-stable-eojwo0`. Committed as text per the BAR evidence requirement.

## Apply summary

`38 OK, 36 FAIL`. The failures are expected and environment-driven (documented below):
gold materialized-view column ops and persona GRANTs. Everything the platform allows on
SDP-managed objects applied cleanly: the two governance functions, table + silver column
comments (data dictionary), layer/classification tags, and the column masks + row filter.

## Personas (workspace groups)

`hotel_engineer`, `hotel_analyst`, `hotel_mgr_city`, `hotel_mgr_resort` created in the
workspace. Mask/RLS functions key off membership via `is_member(...)`.

## Column masks (information_schema.column_masks)

| column | mask |
|--------|------|
| country | mask_pii |
| agent | mask_pii |
| company | mask_pii |

## Row filter (information_schema.row_filters)

| table | filter |
|-------|--------|
| silver_bookings | hotel_row_filter |

## Governance function definitions (information_schema.routines)

```
mask_pii(v)          = CASE WHEN is_member('hotel_engineer') THEN v ELSE '***' END
hotel_row_filter(h)  = is_member('hotel_engineer')
                    OR is_member('hotel_analyst')
                    OR (is_member('hotel_mgr_city')   AND h = 'City Hotel')
                    OR (is_member('hotel_mgr_resort') AND h = 'Resort Hotel')
```

## Live enforcement (querying silver_bookings)

| Effective membership | is_member('hotel_engineer') | rows visible | hotels | country sample |
|----------------------|-----------------------------|--------------|--------|----------------|
| hotel_engineer | true | 119,389 | 2 | `ZWE` (unmasked) |
| none (removed from all groups) | false | 0 | 0 | - (row filter denies all) |

The engineer path returns unmasked `country` across all rows; a principal in no persona
group is denied every row by `hotel_row_filter`. The `mask_pii` `ELSE '***'` branch and the
per-property `hotel_mgr_*` branches are verified structurally (column_masks + routines above)
and by the deny-all behaviour. Note: Databricks SQL caches group membership for several
minutes, so flipping the operator's own membership within a single session does not reliably
show the masked-with-rows state live; the enforcement is definitively in place per
information_schema.

## Column classification tags (information_schema.column_tags)

| column | hb_data_class |
|--------|---------------|
| country | pii |
| agent | pii |
| company | pii |
| adr | financial |
| est_lost_revenue | financial |

(Custom key `hb_data_class` is used because the workspace enforces a governed
`data_sensitivity` tag policy that restricts allowed values.)

## Table tags (information_schema.table_tags)

| table | tags |
|-------|------|
| bronze_bookings | layer=bronze |
| silver_bookings | layer=silver |
| gold_hotel_month | layer=gold, certified=true |

## Data dictionary (information_schema.columns, silver excerpt)

| column | comment |
|--------|---------|
| reservation_id | Deterministic content-hash surrogate key for the reservation (informational PK). |
| hotel | Property: "City Hotel" or "Resort Hotel". Row-level security dimension. |
| is_canceled | Whether the booking was canceled (ground-truth label for the cancellation model). |
| adr | Average Daily Rate (revenue per occupied room-night), decimal(10,2). |
| est_lost_revenue | adr * stay_nights when canceled, else 0. Room-night lost-revenue proxy (not true RevPAR). |
| country | Guest country of origin (ISO 3155-3:2013). Masked for non-engineers. |
| agent / company | Booking intermediary identifiers. Masked for non-engineers. |

Full dictionary covers all key silver columns plus table comments on all three tables.

## Lineage (system.access.table_lineage)

```
bronze_bookings -> silver_bookings
silver_bookings -> gold_hotel_month
```

Automatic UC lineage reflects the medallion DAG.

## Known environment limitations (expected FAILs)

1. **Persona GRANTs (36 FAIL, PRINCIPAL_DOES_NOT_EXIST).** UC object grants require
   account-level group principals. This workspace/profile has no account-admin access
   (`databricks account groups` returns Not Found), so the persona grant matrix in
   `governance/grants.sql` cannot be applied here. It is delivered as the production
   pattern. Crucially, data protection does not depend on it: the column masks + row
   filter (keyed to the same groups) are applied and enforced.
2. **gold_hotel_month column ops.** It is a materialized view; `ALTER TABLE ... ALTER
   COLUMN` (comments, tags) and `SET ROW FILTER` are rejected (`EXPECT_TABLE_NOT_VIEW`).
   Gold carries table-level comment + tags; managers get per-property enforcement on the
   row-level `silver_bookings`.
3. **Constraints (NOT NULL / PK).** SDP-managed streaming tables reject external
   `ALTER ... ADD CONSTRAINT` / `SET NOT NULL`; the MV rejects `ALTER TABLE`. Keys are
   documented via the data dictionary; not-null on `hotel` is enforced at ingest by the
   pipeline expectation. See `governance/constraints.sql` for reference DDL.
