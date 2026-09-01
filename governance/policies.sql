-- Security policies: apply column masks + row-level security.
-- {catalog} / {schema} substituted by governance/apply.sh.
-- Depends on functions.sql (mask_pii, hotel_row_filter) already existing.
-- gold_hotel_month is a materialized view; the row filter is best-effort there.

-- Idempotent: DROP before SET. On a fresh table the DROP statements fail benignly
-- (no mask/filter yet) and apply.sh continues; on a re-run they clear the prior policy
-- so SET succeeds cleanly.

-- Column masks on the PII-ish identifiers (silver).
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN country DROP MASK;
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN agent   DROP MASK;
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN company DROP MASK;
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN country SET MASK {catalog}.{schema}.mask_pii;
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN agent   SET MASK {catalog}.{schema}.mask_pii;
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN company SET MASK {catalog}.{schema}.mask_pii;

-- Per-property row-level security (silver only; gold_hotel_month is an MV and rejects
-- row filters - managers get per-property enforcement on the row-level silver table).
ALTER TABLE {catalog}.{schema}.silver_bookings DROP ROW FILTER;
ALTER TABLE {catalog}.{schema}.silver_bookings SET ROW FILTER {catalog}.{schema}.hotel_row_filter ON (hotel);
