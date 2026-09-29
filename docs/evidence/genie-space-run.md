# Evidence — Genie space "Hotel Booking Cancellation Intelligence"

**Workspace:** fevm-fe-bar-ecastillo
**Catalog/schema:** fe_bar_ecastillo_catalog.hotel_booking_dev
**space_id:** 01f1bc510bc211139339758ac42c1d1a
**warehouse_id:** 94dfd610249e30f5 (Serverless Starter Warehouse)
**Tables:** gold_hotel_month, reservation_risk
**Risk model_version observed:** 1 (all 119,389 scored reservations)
**Run date:** 2026-09-29

All six curated sample questions were asked through the Genie Conversation API
(`ask_genie`). Every question returned `status = COMPLETED` with valid SQL and results.

## Sample question runs

### Q1: What was the cancellation rate for City Hotel by month in 2016?
- Generated SQL:
  ```sql
  SELECT arrival_year, arrival_month, cancel_rate
  FROM fe_bar_ecastillo_catalog.hotel_booking_dev.gold_hotel_month
  WHERE hotel = 'City Hotel'
    AND arrival_year = 2016
    AND cancel_rate IS NOT NULL
  ORDER BY arrival_month
  ```
- Result (12 rows, arrival_month : cancel_rate):
  1:0.3211, 2:0.3922, 3:0.3638, 4:0.4322, 5:0.3906, 6:0.4384, 7:0.3331,
  8:0.3692, 9:0.4048, 10:0.4615, 11:0.4356, 12:0.4326
- Answer: monthly rates ranged 0.3211 (Jan) to 0.4615 (Oct).

### Q2: Which arrival month had the highest estimated lost revenue?
- Generated SQL (RANK() over est_lost_revenue DESC, rev_rank = 1):
  ```sql
  WITH ranked_months AS (
    SELECT hotel, arrival_year, arrival_month, arrival_month_start, est_lost_revenue,
           RANK() OVER (ORDER BY est_lost_revenue DESC) AS rev_rank
    FROM fe_bar_ecastillo_catalog.hotel_booking_dev.gold_hotel_month
    WHERE arrival_month_start IS NOT NULL AND est_lost_revenue IS NOT NULL
  )
  SELECT hotel, arrival_year, arrival_month, arrival_month_start, est_lost_revenue
  FROM ranked_months WHERE rev_rank = 1
  ```
- Result (1 row): City Hotel, 2017-05-01, est_lost_revenue = 878,912.05
- Answer: May 2017 (City Hotel) had the highest estimated lost revenue.

### Q3: How many reservations are high risk per hotel?
- Generated SQL:
  ```sql
  SELECT hotel, COUNT(*) AS high_risk_reservations
  FROM fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk
  WHERE hotel IS NOT NULL AND risk_band IS NOT NULL AND risk_band ILIKE '%high%'
  GROUP BY hotel
  ORDER BY high_risk_reservations DESC, hotel ASC
  ```
- Result (2 rows): City Hotel = 22,147 ; Resort Hotel = 4,667

### Q4: What's the average cancel probability by risk band?
- Generated SQL:
  ```sql
  SELECT risk_band, COUNT(*) AS reservations, AVG(cancel_probability) AS avg_cancel_probability
  FROM fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk
  WHERE risk_band IS NOT NULL
  GROUP BY risk_band
  ORDER BY avg_cancel_probability DESC
  ```
- Result (3 rows): high = 26,814 / 0.9186 ; medium = 14,281 / 0.5374 ; low = 78,294 / 0.1498
- Answer: avg cancel probability rises consistently low → high, matching the band definitions.

### Q5: Compare the cancellation rate between the two hotels.
- Generated SQL:
  ```sql
  SELECT hotel, SUM(bookings) AS total_bookings, SUM(cancellations) AS total_cancellations,
         100 * (try_divide(SUM(cancellations), SUM(bookings))) AS cancellation_rate_pct
  FROM fe_bar_ecastillo_catalog.hotel_booking_dev.gold_hotel_month
  WHERE hotel IN ('City Hotel', 'Resort Hotel')
  GROUP BY hotel
  ORDER BY hotel
  ```
- Result (2 rows): City Hotel = 33,102 / 79,330 = 41.73% ; Resort Hotel = 11,122 / 40,059 = 27.76%
- Answer: City Hotel cancels at 41.73% vs Resort Hotel 27.76%. (Note: the aggregate here
  weights by bookings, which is the correct way to combine per-month `cancel_rate` — the
  space's general instruction warns against unweighted averaging.)

### Q6: What model version produced the current risk scores?
- Generated SQL:
  ```sql
  SELECT model_version, COUNT(*) AS reservations
  FROM fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk
  WHERE model_version IS NOT NULL
  GROUP BY model_version
  ORDER BY reservations DESC, model_version DESC
  LIMIT 1
  ```
- Result (1 row): model_version = 1, reservations = 119,389
- Answer: model_version 1 produced all current risk scores. (Genie also offered a helpful
  follow-up: whether to rank by most-recent `scored_at` instead of row count.)

## Spot-check (ask_genie vs direct SQL)

Direct `execute_sql` (warehouse 94dfd610249e30f5) for the risk-band distribution:

| risk_band | reservations | avg_cancel_probability |
|-----------|--------------|------------------------|
| high      | 26,814       | 0.9186                 |
| medium    | 14,281       | 0.5374                 |
| low       | 78,294       | 0.1498                 |

**Match:** identical to the Q4 `ask_genie` answer (high 0.9186, medium 0.5374, low 0.1498;
counts 26,814 / 14,281 / 78,294). Verification passed.

## Notes

- The space is created and curated entirely from `genie/hotel_booking_space.yaml` (source of
  truth); the full config is captured in `genie/hotel_booking_space.serialized.json`.
- Genie honored the domain grain: risk questions (Q3, Q4, Q6) query `reservation_risk` at the
  per-reservation level (119,389 rows incl. exact-duplicate bookings); trend/KPI questions
  (Q1, Q2, Q5) query the pre-aggregated `gold_hotel_month`.
- Deviation from plan: the space was created via the CLI `data-rooms` API (identical payload to
  the MCP `create_or_update`) because the MCP create path held a stale startup client. Querying
  (`ask_genie`) and export used the working Genie API path.
