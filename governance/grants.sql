-- Persona grants matrix. {catalog} / {schema} substituted by governance/apply.sh.
-- Groups: hotel_engineer, hotel_analyst, hotel_mgr_city, hotel_mgr_resort.
-- Column masks + row filters (see policies.sql) do the per-persona restriction;
-- grants control which tables each persona can read at all.

-- Catalog / schema traversal for every persona.
GRANT USE CATALOG ON CATALOG {catalog} TO `hotel_engineer`;
GRANT USE CATALOG ON CATALOG {catalog} TO `hotel_analyst`;
GRANT USE CATALOG ON CATALOG {catalog} TO `hotel_mgr_city`;
GRANT USE CATALOG ON CATALOG {catalog} TO `hotel_mgr_resort`;

GRANT USE SCHEMA ON SCHEMA {catalog}.{schema} TO `hotel_engineer`;
GRANT USE SCHEMA ON SCHEMA {catalog}.{schema} TO `hotel_analyst`;
GRANT USE SCHEMA ON SCHEMA {catalog}.{schema} TO `hotel_mgr_city`;
GRANT USE SCHEMA ON SCHEMA {catalog}.{schema} TO `hotel_mgr_resort`;

-- Engineers: full control of the schema + read the raw volume + read bronze.
GRANT ALL PRIVILEGES ON SCHEMA {catalog}.{schema} TO `hotel_engineer`;
GRANT READ VOLUME ON VOLUME {catalog}.{schema}.raw TO `hotel_engineer`;

-- Bronze is raw/unmasked: engineers only.
GRANT SELECT ON TABLE {catalog}.{schema}.bronze_bookings TO `hotel_engineer`;

-- Silver: all personas read it; masks + row filter restrict what they see.
GRANT SELECT ON TABLE {catalog}.{schema}.silver_bookings TO `hotel_analyst`;
GRANT SELECT ON TABLE {catalog}.{schema}.silver_bookings TO `hotel_mgr_city`;
GRANT SELECT ON TABLE {catalog}.{schema}.silver_bookings TO `hotel_mgr_resort`;

-- Gold: all personas read it (row filter restricts managers to their property).
GRANT SELECT ON TABLE {catalog}.{schema}.gold_hotel_month TO `hotel_analyst`;
GRANT SELECT ON TABLE {catalog}.{schema}.gold_hotel_month TO `hotel_mgr_city`;
GRANT SELECT ON TABLE {catalog}.{schema}.gold_hotel_month TO `hotel_mgr_resort`;

-- Every persona must be able to EXECUTE the mask + row-filter functions they hit.
GRANT EXECUTE ON FUNCTION {catalog}.{schema}.mask_pii TO `hotel_engineer`;
GRANT EXECUTE ON FUNCTION {catalog}.{schema}.mask_pii TO `hotel_analyst`;
GRANT EXECUTE ON FUNCTION {catalog}.{schema}.mask_pii TO `hotel_mgr_city`;
GRANT EXECUTE ON FUNCTION {catalog}.{schema}.mask_pii TO `hotel_mgr_resort`;

GRANT EXECUTE ON FUNCTION {catalog}.{schema}.hotel_row_filter TO `hotel_engineer`;
GRANT EXECUTE ON FUNCTION {catalog}.{schema}.hotel_row_filter TO `hotel_analyst`;
GRANT EXECUTE ON FUNCTION {catalog}.{schema}.hotel_row_filter TO `hotel_mgr_city`;
GRANT EXECUTE ON FUNCTION {catalog}.{schema}.hotel_row_filter TO `hotel_mgr_resort`;
