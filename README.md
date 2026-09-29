# Hotel Booking Cancellation Intelligence

End-to-end hotel booking cancellation intelligence on Databricks — from raw bookings to real-time risk scoring, natural-language analytics, and a revenue-management app.

## The problem

Hotels lose meaningful revenue to booking cancellations: rooms held for guests who never arrive, released too late to resell. Revenue managers need to know **which reservations are likely to cancel**, **how it moves occupancy and RevPAR**, and **what to do about it** (deposit requests, controlled overbooking, re-confirmation nudges) — in time to act.

This project turns raw booking data into a live, decision-ready workflow across the full Lakehouse.

## Business outcome & KPIs

Lead with the buyer's numbers:

- **Revenue lost to last-minute cancellations** ($)
- **RevPAR** (revenue per available room)
- **Occupancy %** and **on-the-books forecast accuracy**
- **Overbooking accuracy** (rooms recovered without walk-outs)

## Dataset

**Hotel Booking Demand** (Antonio, Almeida & Nunes — public) — ~119K real bookings with an `is_canceled` label and rich features: lead time, deposit type, market segment, ADR, previous cancellations, special requests, country, booking channel.

- Real ground-truth label → defensible model evaluation, no synthesis required.
- Source: [Hotel Booking Demand on Kaggle](https://www.kaggle.com/datasets/jessemostipak/hotel-booking-demand) (`hotel_bookings.csv`). See [data/README.md](data/README.md) for download + Volume landing steps.

## End-to-end journey

| Stage | Component | What it does |
|-------|-----------|--------------|
| **Ingest** | Lakeflow | Land raw bookings into the Lakehouse (bronze), incrementally |
| **Govern** | Unity Catalog | Personas + column masks (country/agent/company), per-property row-level security, data dictionary, classification tags, lineage |
| **Make it intelligent** | ML | Cancellation-probability classifier (sklearn/HistGradientBoosting) on `silver_bookings`; MLflow tracking, UC-registered `hotel_cancel_classifier@champion`, batch `reservation_risk` table + real-time serving endpoint |
| **Serve operationally** | Lakebase | Low-latency store of per-reservation risk scores + recommended actions for the app |
| **Make it queryable** | Genie Room | Natural-language analytics: "expected cancellation rate for December?", "occupancy forecast next month?" |
| **Surface to the business** | Databricks App | Revenue-manager view: at-risk reservations, occupancy impact, recommended actions |

## Architecture

```
raw bookings
   │  Lakeflow (ingest)
   ▼
bronze ─► silver ─► gold   [Unity Catalog: govern, mask PII, lineage]
   │                 │
   │                 ├─► ML: cancellation classifier ─► MLflow ─► UC model ─► serving endpoint
   │                 │              │
   │                 │              ▼
   │                 │        Lakebase (per-reservation risk scores + actions)
   │                 │              │
   │                 │              ▼
   │                 │        Databricks App (revenue-manager UI)
   │                 │
   │                 └─► Genie Room (natural-language analytics)
```
_(refine as the design firms up)_

## Repo layout (proposed)

```
.
├── data/                 # dataset staging / download scripts
├── notebooks/            # ingestion, transformation, ML — committed WITH outputs
├── src/                  # shared code (features, model, serving helpers)
├── app/                  # Databricks App
├── genie/                # Genie room config / example questions
├── infra/                # UC setup, Lakebase, serving endpoint definitions
├── docs/                 # architecture, decisions, deck
└── README.md
```

## Running the Lakeflow ingest

The ingest slice is a serverless Python Lakeflow (Spark Declarative) pipeline packaged
as a Databricks Asset Bundle. Full design: [docs/superpowers/specs/2026-08-28-lakeflow-ingest-design.md](docs/superpowers/specs/2026-08-28-lakeflow-ingest-design.md).

```bash
# 1. Land the CSV in the UC Volume (see data/README.md)
# 2. Deploy + run the bundle (dev target)
databricks bundle validate -t dev -p <profile>
databricks bundle deploy   -t dev -p <profile>
databricks bundle run hotel_booking_ingest_etl -t dev -p <profile>
```

Tables produced in `${catalog}.${schema}`: `bronze_bookings` (Auto Loader raw land),
`silver_bookings` (typed, cleaned, one row per reservation, keyed by `reservation_id`),
`gold_hotel_month` (hotel x month cancel rate, ADR, estimated lost revenue). Catalog/schema
are bundle variables in [databricks.yml](databricks.yml).

## Unity Catalog governance

Governance is authored as idempotent SQL in [governance/](governance/) and applied by
[governance/apply.sh](governance/apply.sh) (SDP can't express grants/masks/tags). Full
design: [docs/superpowers/specs/2026-09-01-unity-catalog-governance-design.md](docs/superpowers/specs/2026-09-01-unity-catalog-governance-design.md).

- Personas: `hotel_engineer` (full, unmasked), `hotel_analyst` (masked PII, all rows),
  `hotel_mgr_city` / `hotel_mgr_resort` (masked PII, row-filtered to their property).
- Dynamic column masks on `country` / `agent` / `company` (`mask_pii`).
- Per-property row-level security on `hotel` (`hotel_row_filter`).
- Column-level data dictionary, `hb_data_class` (pii/financial) + `layer`/`certified` tags,
  and automatic bronze -> silver -> gold lineage.

Two interchangeable runners share the same `governance/*.sql`:

```bash
# Local / CLI runner (needs a SQL warehouse):
PROFILE=<profile> CATALOG=<catalog> SCHEMA=<schema> WAREHOUSE=<warehouse_id> \
  governance/apply.sh

# Re-runnable bundle job (serverless notebook, no warehouse) — for later re-runs:
databricks bundle deploy -t dev -p <profile>
databricks bundle run hotel_booking_governance -t dev -p <profile>
```

The `hotel_booking_governance` job runs
[src/hotel_booking_ingest/governance/apply_governance.py](src/hotel_booking_ingest/governance/apply_governance.py),
a serverless port of `apply.sh` that creates the persona groups, probes the membership
function, and re-applies the bundled `governance/*.sql` idempotently. Full design:
[docs/superpowers/specs/2026-09-01-governance-dab-job-design.md](docs/superpowers/specs/2026-09-01-governance-dab-job-design.md).

Evidence: [docs/evidence/unity-catalog-governance.md](docs/evidence/unity-catalog-governance.md),
[docs/evidence/governance-dab-job-run.md](docs/evidence/governance-dab-job-run.md).
Note: persona GRANTs require account-level groups (production pattern in
[governance/grants.sql](governance/grants.sql)); the mask + row-filter enforcement does not
depend on them.

## Cancellation-probability model

The ML slice trains a cancellation classifier on the governed `silver_bookings` table,
registers it to Unity Catalog, batch-scores every reservation, and serves it in real time.
Full design: [docs/superpowers/specs/2026-09-02-ml-cancel-classifier-design.md](docs/superpowers/specs/2026-09-02-ml-cancel-classifier-design.md).

- Model: sklearn `HistGradientBoostingClassifier` in an one-hot + numeric `Pipeline`,
  trained with an honest **temporal** split (test = latest arrivals). Tracked in MLflow
  (ROC-AUC, PR-AUC, precision/recall/F1, confusion matrix, feature importance) and
  registered as `${catalog}.${schema}.hotel_cancel_classifier@champion`.
- Target-leakage columns (`reservation_status`/`_date`, `est_lost_revenue`) are dropped.
- Batch scoring writes `${catalog}.${schema}.reservation_risk` (`reservation_id`,
  `cancel_probability`, `risk_band`) - the source for Lakebase + the app.
- A scale-to-zero Model Serving endpoint (`hotel-cancel-classifier`) serves `@champion`.

Train and scoring are one chained job (`hotel_cancel_ml`: `train` -> `score`), so the whole
model refresh runs from a single command. Full chained-job design:
[docs/superpowers/specs/2026-09-02-ml-chained-job-design.md](docs/superpowers/specs/2026-09-02-ml-chained-job-design.md).

```bash
# Refresh the model + reservation_risk in one run (train -> score, chained):
databricks bundle run hotel_cancel_ml -t dev -p <profile>

# Deploy the serving endpoint (resolve @champion -> version, pass it in):
V=$(databricks model-versions get-by-alias \
      <catalog>.<schema>.hotel_cancel_classifier champion -p <profile> -o json \
      | python3 -c 'import sys,json;print(json.load(sys.stdin)["version"])')
databricks bundle deploy -t dev -p <profile> --var="cancel_model_version=$V"
```

Evidence: [docs/evidence/ml-cancel-classifier-run.md](docs/evidence/ml-cancel-classifier-run.md)
(dev run: ROC-AUC 0.84, 26.8K bookings flagged high-risk, live endpoint prediction).

## Evidence of execution

The build must be **readable as text**. Commit:

- Notebook cells **with outputs visible** (query results, model metrics, sample predictions)
- Model evaluation: AUC, precision/recall, confusion matrix, feature importances
- Sample Genie question → answer pairs
- Logged run output for pipelines

## Deliverables

- [ ] The build (code, notebooks with outputs, app, Genie room)
- [ ] Evidence of execution committed as text
- [ ] Presentation deck — leads with business outcome, quantifies impact in RevPAR / occupancy / lost-revenue terms

## Open questions / brainstorm

- Target workspace (Lakebase + Genie enabled?)
- Batch vs. streaming ingestion for Lakeflow
- Classic ML only, or add the GenAI recommended-action layer?
- How to frame overbooking recommendation logic (threshold vs. optimization)
- Deck narrative: executive sponsor (revenue/GM) vs. domain owner (revenue manager)

## Time budget (~4–8 hrs)

| Stage | Est. |
|-------|------|
| Ingest + UC setup | 1–1.5 h |
| Transformations (silver/gold) | 1 h |
| ML model + tracking + serving | 1.5–2 h |
| Lakebase serving | 0.5–1 h |
| Genie room | 0.5 h |
| Databricks App | 1–1.5 h |
| Deck | 1 h |
