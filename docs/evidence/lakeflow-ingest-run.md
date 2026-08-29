# Lakeflow ingest — execution evidence

Run of the `hotel_booking_ingest_etl` serverless SDP pipeline (dev target) against
`serverless_stable_eojwo0_catalog.hotel_booking_dev` on
`fevm-serverless-stable-eojwo0`. Committed as text per the BAR "evidence of execution"
requirement.

## Pipeline run (update eb3ff2 — COMPLETED)

All three flows completed in one update:

```
Update eb3ff2 is INITIALIZING.
Update eb3ff2 is SETTING_UP_TABLES.
Update eb3ff2 is RUNNING.
Flow '...bronze_bookings' has COMPLETED.
Flow '...silver_bookings' has COMPLETED.
Flow '...gold_hotel_month' has COMPLETED.
Update eb3ff2 is COMPLETED.
```

DAG: `bronze_bookings` (Auto Loader) -> `silver_bookings` (typed + expectations) ->
`gold_hotel_month` (materialized view).

## Row counts — ingest fidelity

| Metric | Value |
|--------|-------|
| CSV data rows (local) | 119,390 |
| `bronze_bookings` | 119,390 |
| `silver_bookings` | 119,389 |

Bronze matches the source CSV exactly. Silver drops exactly 1 row via the
`non_negative_adr` (`adr >= 0`) expectation — the dataset's known negative-ADR record
(`adr = -6.38`). Zero rows had a null `hotel`.

## Silver sample (typed + derived columns)

```
hotel       is_canceled  arrival_date  lead_time  adr     stay_nights  est_lost_revenue
City Hotel  true         2015-07-01    257        101.50  2            203.00
City Hotel  true         2015-07-01    257        101.50  2            203.00
...
```

`arrival_date` (from year + month name + day), `stay_nights` (weekend + week nights),
and `est_lost_revenue` (`adr * stay_nights` when canceled) are all derived in silver.

## Gold KPIs — hotel x arrival month (first City Hotel months)

| hotel | month | bookings | cancellations | cancel_rate | avg_adr | room_nights | est_lost_revenue |
|-------|-------|----------|---------------|-------------|---------|-------------|------------------|
| City Hotel | 2015-07 | 1398 | 939 | 0.6717 | 69.82 | 3766 | 181,952.17 |
| City Hotel | 2015-08 | 2480 | 1232 | 0.4968 | 77.73 | 6750 | 237,178.37 |
| City Hotel | 2015-09 | 3529 | 1543 | 0.4372 | 101.06 | 9641 | 439,562.20 |
| City Hotel | 2015-10 | 3386 | 1321 | 0.3901 | 89.39 | 8856 | 283,480.47 |
| City Hotel | 2015-11 | 1235 | 301 | 0.2437 | 73.54 | 3591 | 77,033.62 |
| City Hotel | 2015-12 | 1654 | 668 | 0.4039 | 81.11 | 4895 | 178,177.68 |
| City Hotel | 2016-01 | 1364 | 438 | 0.3211 | 76.33 | 3747 | 114,680.79 |
| City Hotel | 2016-02 | 2371 | 930 | 0.3922 | 79.98 | 6750 | 227,680.56 |

## Headline — estimated lost revenue to cancellations, by hotel

| hotel | bookings | cancel_rate | total_est_lost_revenue |
|-------|----------|-------------|------------------------|
| City Hotel | 79,330 | 0.4173 | 10,885,059.78 |
| Resort Hotel | 40,059 | 0.2776 | 5,842,177.34 |

City Hotel cancels ~42% of bookings (~$10.9M estimated lost room-night revenue) vs
Resort Hotel ~28% (~$5.8M). This is the number the downstream ML / app / Genie stages
will act on. Note the honest limit: `est_lost_revenue` is a room-night proxy
(`adr * nights`), not true RevPAR, which needs room inventory the dataset lacks.
