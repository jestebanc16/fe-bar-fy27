-- Validation / evidence queries for the hotel booking Lakeflow ingest.
-- Run against the deployed catalog.schema (bundle variables). Replace {catalog}/{schema}.

-- 1. Bronze row count (should match the CSV: ~119,390 rows).
SELECT count(*) AS bronze_rows FROM {catalog}.{schema}.bronze_bookings;

-- 2. Any malformed rows captured by Auto Loader rescue?
SELECT count(*) AS rescued_rows
FROM {catalog}.{schema}.bronze_bookings
WHERE _rescued_data IS NOT NULL;

-- 3. Silver row count + how many rows were dropped by expectations vs bronze.
SELECT
  (SELECT count(*) FROM {catalog}.{schema}.bronze_bookings) AS bronze_rows,
  count(*) AS silver_rows
FROM {catalog}.{schema}.silver_bookings;

-- 4. Silver sample: typed columns + derived fields.
SELECT hotel, is_canceled, arrival_date, lead_time, adr, stay_nights, est_lost_revenue
FROM {catalog}.{schema}.silver_bookings
ORDER BY arrival_date
LIMIT 20;

-- 5. Gold KPIs: both hotels, first months.
SELECT hotel, arrival_month_start, bookings, cancellations, cancel_rate, avg_adr,
       room_nights, canceled_room_nights, est_lost_revenue
FROM {catalog}.{schema}.gold_hotel_month
ORDER BY hotel, arrival_month_start
LIMIT 24;

-- 6. Headline: total estimated lost revenue to cancellations, by hotel.
SELECT hotel,
       sum(bookings) AS bookings,
       round(sum(cancellations) / sum(bookings), 4) AS cancel_rate,
       sum(est_lost_revenue) AS total_est_lost_revenue
FROM {catalog}.{schema}.gold_hotel_month
GROUP BY hotel
ORDER BY total_est_lost_revenue DESC;
