# Lakeflow ingest for hotel booking demand — design

Status: approved 2026-08-28. Scope: the Lakeflow (ingest) slice only. ML, Lakebase,
Genie, and the Databricks App are out of scope for this iteration.

## Goal

Land the Kaggle [Hotel Booking Demand](https://www.kaggle.com/datasets/jessemostipak/hotel-booking-demand)
dataset (`hotel_bookings.csv`, ~119K rows x 32 columns) into the Lakehouse with a
single serverless Python Lakeflow Spark Declarative Pipeline (SDP) that builds a
bronze -> silver -> gold medallion in one Unity Catalog schema.

## Locked decisions

- Source: `hotel_bookings.csv`, a static file (bookings July 2015 - August 2017 for
  one city hotel and one resort hotel). Not a live feed.
- Ingest: one-shot Auto Loader (`cloudFiles`, `csv`) from a UC Volume into a bronze
  streaming table. Auto Loader still incrementally picks up any future files dropped
  in the same path.
- Full medallion in this one pipeline: bronze + silver + one gold.
- Gold grain: hotel x arrival month.
- Language: Python SDP (`from pyspark import pipelines as dp` — not legacy `import dlt`).
- Unity Catalog: one catalog, one schema, prefixed tables `bronze_bookings`,
  `silver_bookings`, `gold_hotel_month`.
- Packaging: a Databricks Asset Bundle (DAB) at repo root so the later App/Genie can
  join the same `databricks.yml`.

The catalog and schema are deploy-time bundle variables so the same code runs against
a personal sandbox or a shared catalog.

## Data flow

```
Kaggle CSV
  -> UC Volume  /Volumes/{catalog}/{schema}/raw/hotel_bookings/
  -> bronze_bookings   (streaming table, Auto Loader, append + file lineage)
  -> silver_bookings   (streaming table, typed + cleaned, one row per reservation)
  -> gold_hotel_month  (materialized view, hotel x month KPIs)
```

## Tables

### bronze_bookings (streaming table)

- Auto Loader `cloudFiles` reading `csv` with `header=true`,
  `cloudFiles.inferColumnTypes=true`, and `rescuedDataColumn=_rescued_data`.
- Adds `_ingested_at` (`current_timestamp()`) and `_source_file`
  (`_metadata.file_path`).
- Minimal transforms; append-only; auditable raw land + file lineage.

### silver_bookings (streaming table)

- Reads `spark.readStream.table("bronze_bookings")`.
- Type casting: `is_canceled` boolean, counts to int, `adr` to `DECIMAL(10,2)`.
- Derived columns:
  - `arrival_date` from `arrival_date_year` + month name + `arrival_date_day_of_month`.
  - `stay_nights = stays_in_weekend_nights + stays_in_week_nights`.
  - `est_lost_revenue = adr * stay_nights` when canceled, else 0.
- Data-quality expectations:
  - `@dp.expect_or_drop` non-null `hotel`.
  - `@dp.expect_or_drop` `adr >= 0`.
  - `@dp.expect` at least one guest (`adults + children + babies > 0`) — warn only.
  - `@dp.expect` clean parse (`_rescued_data IS NULL`) — warn only.
- One row per reservation. This is the grain ML will read later — no separate
  reservation-level gold.

### gold_hotel_month (materialized view)

- `@dp.materialized_view`, full-table aggregate (not a streaming window) from silver.
- Grain: `hotel`, `arrival_year`, `arrival_month`, plus a sortable
  `arrival_month_start` date.
- Metrics: `bookings`, `cancellations`, `cancel_rate`, `avg_adr`, `room_nights`,
  `canceled_room_nights`, `est_lost_revenue`.
- Honest limit: true occupancy / RevPAR need room inventory, which the dataset lacks.
  This gold supports lost revenue + cancel rate and a room-night proxy only.

## Landing the data

- Do NOT commit the 119K-row CSV to git (Kaggle license + size). `data/` holds only a
  README + optional download helper.
- Steps: download `hotel_bookings.csv` from Kaggle, then
  `databricks fs cp hotel_bookings.csv dbfs:/Volumes/{catalog}/{schema}/raw/hotel_bookings/`.

## Error handling and quality

- Bronze keeps bad rows via `_rescued_data`.
- Silver drops the hard-invalid rows (null hotel, negative ADR) and warns on the soft
  ones. No separate quarantine table unless rescue volume proves non-trivial (YAGNI).
- Re-runs are idempotent: streaming tables + managed pipeline checkpoints mean a
  re-dropped file is not double-counted; the gold MV recomputes from silver.

## Packaging / compute

- Serverless SDP (default).
- DAB scaffolded with `databricks pipelines init` (standalone pipeline project).
- Single schema on the pipeline `schema` parameter; table names are prefixed, not
  separate `bronze` / `silver` schemas.

## Evidence (BAR)

- Pipeline run with the DAG visible.
- Query cells with outputs: bronze row count vs CSV, silver sample, gold KPIs for
  both hotels across a few months.

## Explicitly not in this slice

CSV date-splitting, Kafka, CDC / SCD2, three UC schemas, SQL pipeline, ML feature
tables, Lakebase, Genie, the App.
