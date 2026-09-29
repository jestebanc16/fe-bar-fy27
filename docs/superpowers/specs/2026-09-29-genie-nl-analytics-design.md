# Genie Natural-Language Analytics — Design

**Date:** 2026-09-29
**Slice:** Genie (natural-language analytics layer)
**Status:** Approved design → ready for implementation plan
**Workspace / catalog:** `fevm-fe-bar-ecastillo` · `fe_bar_ecastillo_catalog.hotel_booking_dev`

## Purpose & scope

A single **dev** Genie space, **"Hotel Booking Cancellation Intelligence"**, providing
natural-language analytics over the project's gold KPI table and ML risk scores. It answers
two question families:

- **Retrospective revenue-management** — e.g. "cancel rate for City Hotel in December?",
  "which month had the most lost revenue?" (backed by `gold_hotel_month`).
- **Forward-looking risk** — e.g. "how many high-risk reservations at Resort Hotel?",
  "average cancel probability by risk band?" (backed by `reservation_risk`).

Scope is **one space over two tables**. No dashboards, no cross-table ML, no prod space
(deferred — the committed serialized lockfile makes prod migration a later `import` if wanted).

### Success criteria

1. The space is created **idempotently** (by display name) via the `manage_genie` MCP tool.
2. Its configuration is committed as **two artifacts**: a readable source-of-truth config and
   an exported serialized lockfile.
3. The curated sample questions return correct SQL + results, **verified via `ask_genie`** and
   captured as an evidence transcript, with at least one numeric answer cross-checked against a
   direct `execute_sql`.

## Key architectural reality

Genie spaces are **not** a Databricks Asset Bundle resource (the bundle supports jobs,
pipelines, `database_instances`, `synced_database_tables`, `apps`, etc. — but not Genie).
Unlike the ingest / governance / ML / Lakebase slices, this slice therefore lives **outside**
`databricks.yml` / `resources/`. Reproducibility comes from committed config + serialized
export plus the idempotent `manage_genie create_or_update` call, not from `bundle deploy`.

## Approach (selected: A — config-as-source, export-as-lockfile)

Author the curated space in a readable, versioned config file (source-of-truth / intent). A
small idempotent builder issues the `manage_genie create_or_update` call from that config.
Then `export` the live space and commit the resulting `serialized_space` JSON as a
lockfile/backup for exact re-import and cross-workspace migration.

- The **config** is the reviewable source of truth (tables, description, instructions, curated
  SQL, sample questions).
- The **serialized lockfile** is the exact snapshot; regenerate it whenever the space changes.

Rejected alternatives: **B (serialized-only)** — one opaque artifact, poor as documentation;
**C (dev+prod parity)** — double the work and the prod schema/tables aren't populated yet,
over-scoped for the current capstone.

## Architecture & artifacts

New top-level `genie/` directory (outside `resources/` since Genie is not a bundle resource):

| Artifact | Role |
|----------|------|
| `genie/hotel_booking_space.yaml` | **Source-of-truth (readable):** display_name, warehouse handling, `table_identifiers`, description, general instructions, curated SQL examples, sample questions. |
| `genie/hotel_booking_space.serialized.json` | **Lockfile:** exported `serialized_space` from the live space, for exact re-import / migration. |
| `genie/build_space.py` | Small idempotent builder: reads the YAML and drives the `manage_genie create_or_update` call (documented, MCP-driven); reminds to re-export afterward. |
| `docs/evidence/genie-space-run.md` | The `ask_genie` Q → SQL → answer transcript + spot-check. |
| `README.md` (extend) | Add `space_id`, tables, and how to rebuild / query, under the existing Genie framing. |

> Note on `build_space.py`: the actual space creation is performed through the workspace-scoped
> `manage_genie` MCP tool (which auto-detects the warehouse). The script encodes/loads the
> config and documents the exact call; it is not a standalone REST client. This keeps a single,
> reviewable path and avoids duplicating credential handling.

## Curated space content

**Tables:**
- `fe_bar_ecastillo_catalog.hotel_booking_dev.gold_hotel_month`
- `fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk`

**Table schemas (for reference):**
- `gold_hotel_month`: `hotel, arrival_year, arrival_month, arrival_month_start, bookings,
  cancellations, cancel_rate, avg_adr, room_nights, canceled_room_nights, est_lost_revenue`
- `reservation_risk`: `reservation_id, hotel, cancel_probability, risk_band, model_version,
  scored_at`

**General instructions (domain context) to embed in the space:**
- `cancel_rate` = share of bookings canceled (0–1), pre-aggregated per hotel × arrival month.
- `risk_band` thresholds: **high** ≥ 0.70, **medium** ≥ 0.40, else **low** (derived from
  `cancel_probability`).
- `est_lost_revenue` = estimated revenue lost to cancellations (ADR × canceled room-nights
  proxy); `room_nights` is a proxy, not audited occupancy.
- **Honest limit:** true occupancy / RevPAR require room-inventory the dataset lacks; do not
  fabricate occupancy or availability answers.
- **Join / grain note:** `reservation_risk.hotel` and `gold_hotel_month.hotel` share hotel
  names. `reservation_risk` has **no per-reservation date**, so risk questions are aggregate /
  hotel-level, not time-series. `gold_hotel_month` is the time-series (by arrival month) table.

**Curated SQL examples (few-shot, ~3):**
1. Monthly cancel rate + estimated lost revenue for a named hotel, ordered by month.
2. Risk-band distribution with average `cancel_probability` from `reservation_risk`.
3. Top arrival months by `est_lost_revenue`.

**Sample questions (~6):**
- "What was the cancellation rate for City Hotel by month in 2016?"
- "Which arrival month had the highest estimated lost revenue?"
- "How many reservations are high risk per hotel?"
- "What's the average cancel probability by risk band?"
- "Compare the cancellation rate between the two hotels."
- "What model version produced the current risk scores?"

## Build / refresh workflow

1. **Create/update** the space via `manage_genie action=create_or_update` from the YAML config
   (warehouse auto-detected; resolved `warehouse_id` + returned `space_id` recorded). Idempotent
   by `display_name`.
2. **Export** the live space via `manage_genie action=export` → write
   `genie/hotel_booking_space.serialized.json`.
3. **Verify** with `ask_genie` (see Evidence).
4. **Commit** config + serialized lockfile + evidence + README update.

Later re-create / migrate = `manage_genie action=import` with the serialized lockfile (catalog
remap for a future prod space). No secrets involved; all via the workspace-scoped MCP.

## Evidence & verification

Run each sample question through `ask_genie`, capturing **question → generated SQL → returned
columns/rows** into `docs/evidence/genie-space-run.md`. Include:
- A **spot-check**: at least one numeric answer cross-verified against a direct `execute_sql`
  on the same table (e.g., a hotel's monthly cancel rate).
- Recorded metadata: `space_id`, `warehouse_id`, table list, and the `model_version` observed in
  the risk answers.

## Error handling & edge cases

- **Warehouse auto-detect fails / none running:** record the explicit `warehouse_id` in the
  config and pass it to `create_or_update`.
- **`ask_genie` returns no SQL / low confidence for a question:** treat as a signal to improve
  the general instructions or add a curated SQL example; re-run and re-export. Document any
  question Genie could not answer well rather than hiding it.
- **Idempotency:** re-running `create_or_update` updates the existing space (matched by display
  name) rather than creating duplicates; the serialized lockfile is regenerated on each change.
- **Occupancy/RevPAR-style questions:** the instructions steer Genie to decline / caveat rather
  than invent numbers.

## Out of scope / honest limits

- No prod Genie space, no AI/BI dashboard, no Agent/Supervisor wiring, no write-back.
- Answer quality depends on Genie's own modeling; curated instructions + examples mitigate but
  don't guarantee every phrasing.
- Occupancy / RevPAR remain out of reach (room inventory not in the dataset).
- `reservation_risk` has no per-reservation date → risk answers are aggregate / hotel-level, not
  time-series.
