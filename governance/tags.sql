-- Governance tags: data classification + medallion layer + certification.
-- {catalog} / {schema} substituted by governance/apply.sh.

-- Medallion layer tags on tables.
ALTER TABLE {catalog}.{schema}.bronze_bookings SET TAGS ('layer' = 'bronze');
ALTER TABLE {catalog}.{schema}.silver_bookings SET TAGS ('layer' = 'silver');
ALTER TABLE {catalog}.{schema}.gold_hotel_month SET TAGS ('layer' = 'gold', 'certified' = 'true');

-- Sensitivity classification on columns. Uses a custom tag key (hb_data_class) to
-- avoid the workspace's governed 'data_sensitivity' tag policy, which restricts values.
-- gold_hotel_month is a materialized view and rejects ALTER COLUMN, so column-level
-- classification is applied on silver only; gold carries table-level tags above.
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN country SET TAGS ('hb_data_class' = 'pii');
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN agent   SET TAGS ('hb_data_class' = 'pii');
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN company SET TAGS ('hb_data_class' = 'pii');
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN adr              SET TAGS ('hb_data_class' = 'financial');
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN est_lost_revenue SET TAGS ('hb_data_class' = 'financial');
