-- Data dictionary: table + column comments. High leverage for the later Genie room.
-- {catalog} / {schema} substituted by governance/apply.sh.

------------------------------------------------------------------------------------
-- bronze_bookings
------------------------------------------------------------------------------------
COMMENT ON TABLE {catalog}.{schema}.bronze_bookings IS
  'Bronze: raw hotel bookings landed from CSV via Auto Loader. Append-only, engineer-only.';

------------------------------------------------------------------------------------
-- silver_bookings (one row per reservation)
------------------------------------------------------------------------------------
COMMENT ON TABLE {catalog}.{schema}.silver_bookings IS
  'Silver: typed, validated hotel bookings, one row per reservation. Governed with PII column masks and per-property row-level security.';

ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN reservation_id COMMENT 'Deterministic content-hash surrogate key for the reservation (informational PK).';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN hotel COMMENT 'Property: "City Hotel" or "Resort Hotel". Row-level security dimension.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN is_canceled COMMENT 'Whether the booking was canceled (ground-truth label for the cancellation model).';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN lead_time COMMENT 'Days between booking date and arrival date.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN arrival_date COMMENT 'Arrival date, derived from year + month name + day of month.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN arrival_year COMMENT 'Arrival year (int).';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN stay_nights COMMENT 'Total nights = weekend nights + week nights.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN adr COMMENT 'Average Daily Rate (revenue per occupied room-night), decimal(10,2).';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN est_lost_revenue COMMENT 'adr * stay_nights when canceled, else 0. Room-night lost-revenue proxy (not true RevPAR).';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN country COMMENT 'Guest country of origin (ISO 3155-3:2013). Masked for non-engineers.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN agent COMMENT 'Travel agency identifier. Masked for non-engineers.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN company COMMENT 'Booking company identifier. Masked for non-engineers.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN market_segment COMMENT 'Market segment (e.g. Online TA, Direct, Corporate).';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN distribution_channel COMMENT 'Booking distribution channel.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN deposit_type COMMENT 'Deposit type: No Deposit, Non Refund, or Refundable.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN customer_type COMMENT 'Booking type: Transient, Transient-Party, Contract, or Group.';
ALTER TABLE {catalog}.{schema}.silver_bookings ALTER COLUMN previous_cancellations COMMENT 'Count of prior bookings the customer canceled.';

------------------------------------------------------------------------------------
-- gold_hotel_month (hotel x arrival month KPIs)
------------------------------------------------------------------------------------
COMMENT ON TABLE {catalog}.{schema}.gold_hotel_month IS
  'Gold: cancellation and revenue KPIs per hotel and arrival month. Certified for BI / Genie.';

ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN hotel COMMENT 'Property: "City Hotel" or "Resort Hotel". Row-level security dimension.';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN arrival_year COMMENT 'Arrival year.';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN arrival_month COMMENT 'Arrival month number (1-12).';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN arrival_month_start COMMENT 'First day of the arrival month (sortable month key).';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN bookings COMMENT 'Total bookings for the hotel-month.';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN cancellations COMMENT 'Count of canceled bookings.';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN cancel_rate COMMENT 'cancellations / bookings (0-1).';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN avg_adr COMMENT 'Average ADR across bookings in the hotel-month.';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN room_nights COMMENT 'Sum of stay_nights across bookings.';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN canceled_room_nights COMMENT 'Sum of stay_nights on canceled bookings.';
ALTER TABLE {catalog}.{schema}.gold_hotel_month ALTER COLUMN est_lost_revenue COMMENT 'Sum of est_lost_revenue (room-night lost-revenue proxy).';
