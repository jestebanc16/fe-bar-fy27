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
| **Govern** | Unity Catalog | Bronze/silver/gold tables, guest PII masking, lineage |
| **Make it intelligent** | ML (+ optional GenAI) | Cancellation-probability classifier; MLflow tracking, UC-registered model, serving endpoint. Optional: LLM-generated recommended action per flagged reservation |
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
`silver_bookings` (typed, cleaned, one row per reservation), `gold_hotel_month`
(hotel x month cancel rate, ADR, estimated lost revenue). Catalog/schema are bundle
variables in [databricks.yml](databricks.yml).

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
