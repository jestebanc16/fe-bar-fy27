# Genie natural-language analytics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a single dev Genie space, "Hotel Booking Cancellation Intelligence", over `gold_hotel_month` + `reservation_risk`, with its config committed as a readable source-of-truth + an exported serialized lockfile, and its answers verified via `ask_genie` and captured as evidence.

**Architecture:** Genie is NOT a Databricks Asset Bundle resource, so this slice lives outside `databricks.yml`/`resources/` in a new top-level `genie/` directory. A readable YAML config is the source of truth; a small loader (`build_space.py`) validates it and emits the exact `manage_genie create_or_update` arguments. The orchestrator creates the space via the `manage_genie` MCP tool, adds general instructions + curated SQL examples in the Genie UI (the MCP `create_or_update` surface does not expose those), then `export`s the full config to a committed serialized lockfile. Sample questions are run through `ask_genie` and captured as evidence.

**Tech Stack:** Databricks Genie (Conversation API + Spaces), `manage_genie`/`ask_genie`/`execute_sql` MCP tools (workspace `fevm-fe-bar-ecastillo`), Python 3 + PyYAML for the config loader.

## Global Constraints

- Workspace / catalog: `fevm-fe-bar-ecastillo` · `fe_bar_ecastillo_catalog.hotel_booking_dev`.
- Tables exposed (exactly two, fully qualified): `fe_bar_ecastillo_catalog.hotel_booking_dev.gold_hotel_month`, `fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk`.
- Genie is **not** a bundle resource — no `resources/*.yml`, no `bundle deploy` for this slice. All artifacts live under `genie/` + `docs/evidence/`.
- Two artifacts are the reproducible source of truth: `genie/hotel_booking_space.yaml` (readable intent) and `genie/hotel_booking_space.serialized.json` (exact export lockfile). Regenerate the serialized file whenever the space changes.
- **Tool reality:** `manage_genie action=create_or_update` accepts only `display_name`, `table_identifiers`, `description`, `sample_questions`, `warehouse_id`, `serialized_space`. **General instructions and curated SQL example queries are NOT settable through that call** — they are added in the Genie UI after baseline creation and then captured by `manage_genie action=export` (which "preserves instructions/SQL examples"). The plan follows that order.
- **Orchestrator-run tasks:** Tasks 3 and 4 call the `manage_genie`/`ask_genie`/`execute_sql` MCP tools and touch the Genie UI. These are run by the main session (the same way the Lakebase deploys/runs were), not by a code subagent. Tasks 1, 2, and 5 are pure file authoring and are subagent-friendly. There is no pytest harness; verification is running the loader, `manage_genie get`, `ask_genie`, and `execute_sql` spot-checks.
- Table schemas (verbatim):
  - `gold_hotel_month`: `hotel, arrival_year, arrival_month, arrival_month_start, bookings, cancellations, cancel_rate, avg_adr, room_nights, canceled_room_nights, est_lost_revenue`
  - `reservation_risk`: `reservation_id, hotel, cancel_probability, risk_band, model_version, scored_at` (`risk_band`: high ≥ 0.70, medium ≥ 0.40, else low)
- Commit after each task. Commits/writes run with `required_permissions=["all"]` (repo pre-commit hooks run).

---

### Task 1: `genie/hotel_booking_space.yaml` — readable source-of-truth config

**Files:**
- Create: `genie/hotel_booking_space.yaml`

**Interfaces:**
- Produces: a YAML document with top-level keys `display_name` (str), `warehouse_id` (str|null), `table_identifiers` (list[str], fully qualified), `description` (str), `instructions` (str, multi-line domain context — applied in UI), `curated_sql` (list of `{title, sql}` — applied in UI), `sample_questions` (list[str]). Consumed by `genie/build_space.py` (Task 2) and by the orchestrator (Tasks 3–4).

- [ ] **Step 1: Write the config file**

Create `genie/hotel_booking_space.yaml`:

```yaml
# Genie space: Hotel Booking Cancellation Intelligence (dev)
# Source-of-truth config. Genie is not a bundle resource; see
# docs/superpowers/specs/2026-09-29-genie-nl-analytics-design.md.
#
# `display_name`, `table_identifiers`, `description`, `sample_questions`, and
# `warehouse_id` are applied via `manage_genie action=create_or_update`.
# `instructions` and `curated_sql` are applied in the Genie UI (the MCP
# create_or_update surface does not expose them), then captured by
# `manage_genie action=export` into hotel_booking_space.serialized.json.

display_name: "Hotel Booking Cancellation Intelligence"

# null => manage_genie auto-detects a running SQL warehouse; the resolved id is
# recorded in the evidence doc. Set an explicit id here if auto-detect fails.
warehouse_id: null

table_identifiers:
  - "fe_bar_ecastillo_catalog.hotel_booking_dev.gold_hotel_month"
  - "fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk"

description: >-
  Natural-language analytics for hotel booking cancellations. Monthly
  revenue-management KPIs (cancellation rate, average ADR, estimated lost
  revenue) come from gold_hotel_month; forward-looking ML cancellation risk
  (cancel_probability, risk_band) comes from reservation_risk.

instructions: |
  This space answers two kinds of questions about hotel booking cancellations.

  GLOSSARY
  - cancel_rate (gold_hotel_month): share of bookings canceled, 0-1, already
    aggregated per hotel and arrival month. Do not re-average it across months
    without weighting by `bookings`.
  - est_lost_revenue (gold_hotel_month): estimated revenue lost to
    cancellations (ADR x canceled room-night proxy). It is an estimate.
  - room_nights / canceled_room_nights (gold_hotel_month): room-night proxies,
    not audited occupancy.
  - cancel_probability (reservation_risk): model score 0-1 that a reservation
    cancels.
  - risk_band (reservation_risk): high when cancel_probability >= 0.70, medium
    when >= 0.40, otherwise low.
  - model_version (reservation_risk): the champion model version that produced
    the scores.

  GRAIN & JOINS
  - gold_hotel_month is the time-series table: one row per hotel x arrival month
    (use arrival_year + arrival_month, or arrival_month_start).
  - reservation_risk is per-reservation and has NO date column. Risk questions
    are aggregate / hotel-level (e.g. counts per risk_band per hotel), not
    time-series. Do not attempt to trend risk over time.
  - hotel values ("City Hotel", "Resort Hotel") are shared across both tables.

  HONEST LIMITS
  - True occupancy and RevPAR require room-inventory the dataset does not
    contain. Do NOT invent occupancy, availability, or RevPAR figures; if asked,
    explain the limitation and offer the closest supported metric (cancel_rate,
    room_nights proxy, est_lost_revenue).

curated_sql:
  - title: "Monthly cancel rate and lost revenue for a hotel"
    sql: |
      SELECT arrival_year, arrival_month, cancel_rate, est_lost_revenue
      FROM fe_bar_ecastillo_catalog.hotel_booking_dev.gold_hotel_month
      WHERE hotel = 'City Hotel'
      ORDER BY arrival_year, arrival_month
  - title: "Risk-band distribution with average cancel probability"
    sql: |
      SELECT risk_band,
             count(*) AS reservations,
             round(avg(cancel_probability), 4) AS avg_cancel_probability
      FROM fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk
      GROUP BY risk_band
      ORDER BY avg_cancel_probability DESC
  - title: "Top arrival months by estimated lost revenue"
    sql: |
      SELECT hotel, arrival_year, arrival_month, est_lost_revenue
      FROM fe_bar_ecastillo_catalog.hotel_booking_dev.gold_hotel_month
      ORDER BY est_lost_revenue DESC
      LIMIT 10

sample_questions:
  - "What was the cancellation rate for City Hotel by month in 2016?"
  - "Which arrival month had the highest estimated lost revenue?"
  - "How many reservations are high risk per hotel?"
  - "What's the average cancel probability by risk band?"
  - "Compare the cancellation rate between the two hotels."
  - "What model version produced the current risk scores?"
```

- [ ] **Step 2: Verify the YAML parses and has the required shape**

Run:
```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && python3 -c "
import yaml
c = yaml.safe_load(open('genie/hotel_booking_space.yaml'))
assert c['display_name'] == 'Hotel Booking Cancellation Intelligence'
assert len(c['table_identifiers']) == 2
assert all(t.count('.') == 2 for t in c['table_identifiers'])
assert len(c['sample_questions']) == 6
assert len(c['curated_sql']) == 3
assert 'HONEST LIMITS' in c['instructions']
print('config OK')
"
```
Expected: `config OK`

- [ ] **Step 3: Commit**

```bash
git add genie/hotel_booking_space.yaml
git commit -m "feat(genie): add Genie space source-of-truth config"
```

---

### Task 2: `genie/build_space.py` — config loader + args emitter

**Files:**
- Create: `genie/build_space.py`

**Interfaces:**
- Consumes: `genie/hotel_booking_space.yaml` (Task 1).
- Produces: functions `load_config(path) -> dict` (validates required keys, fully-qualified table identifiers) and `create_or_update_args(cfg) -> dict` (returns `{action, display_name, table_identifiers, description, sample_questions[, warehouse_id]}`). CLI prints those args as JSON to stdout and the UI-curation + export reminder to stderr; exit code 0 on success, non-zero on invalid config.

- [ ] **Step 1: Write the loader script**

Create `genie/build_space.py`:

```python
"""Load the Genie space config and emit `manage_genie create_or_update` arguments.

Genie spaces are NOT a Databricks Asset Bundle resource, so this slice lives outside
resources/. This script is the reproducible loader: it validates
genie/hotel_booking_space.yaml and prints the exact arguments to pass to the
`manage_genie` MCP tool (action=create_or_update). It is intentionally NOT a REST
client -- space creation runs through the workspace-scoped manage_genie MCP tool, and
general instructions + curated SQL examples are applied in the Genie UI (the
create_or_update surface does not expose them) then captured by
`manage_genie action=export` into hotel_booking_space.serialized.json.

Usage:
    python genie/build_space.py [--config genie/hotel_booking_space.yaml]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

REQUIRED_KEYS = ("display_name", "table_identifiers", "description", "sample_questions")


def load_config(path: pathlib.Path) -> dict:
    cfg = yaml.safe_load(path.read_text())
    missing = [k for k in REQUIRED_KEYS if not cfg.get(k)]
    if missing:
        raise SystemExit(f"config missing required keys: {missing}")
    tables = cfg["table_identifiers"]
    if not isinstance(tables, list) or not tables:
        raise SystemExit("table_identifiers must be a non-empty list")
    for t in tables:
        if t.count(".") != 2:
            raise SystemExit(f"table identifier not fully qualified (catalog.schema.table): {t}")
    return cfg


def create_or_update_args(cfg: dict) -> dict:
    args = {
        "action": "create_or_update",
        "display_name": cfg["display_name"],
        "table_identifiers": cfg["table_identifiers"],
        "description": " ".join(cfg["description"].split()),
        "sample_questions": cfg["sample_questions"],
    }
    if cfg.get("warehouse_id"):
        args["warehouse_id"] = cfg["warehouse_id"]
    return args


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="genie/hotel_booking_space.yaml")
    ns = ap.parse_args()
    cfg = load_config(pathlib.Path(ns.config))
    print(json.dumps(create_or_update_args(cfg), indent=2))
    print(
        "\n# Next steps (orchestrator, via MCP + Genie UI):\n"
        "#  1. Pass the JSON above to manage_genie (action=create_or_update).\n"
        "#  2. In the Genie UI, add the `instructions` text and each `curated_sql`\n"
        "#     example from the config as general instructions / example queries.\n"
        "#  3. Run manage_genie action=export -> genie/hotel_booking_space.serialized.json",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the loader against the real config**

Run:
```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && python3 genie/build_space.py
```
Expected: JSON on stdout whose `action` is `create_or_update`, `display_name` is `Hotel Booking Cancellation Intelligence`, and `table_identifiers` lists exactly the two `fe_bar_ecastillo_catalog.hotel_booking_dev` tables; the UI/export reminder prints to stderr; exit code 0.

- [ ] **Step 3: Verify it rejects a bad config**

Run:
```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && printf 'display_name: X\ntable_identifiers:\n  - not_qualified\ndescription: d\nsample_questions: [q]\n' > /tmp/bad_genie.yaml && python3 genie/build_space.py --config /tmp/bad_genie.yaml; echo "exit=$?"; rm -f /tmp/bad_genie.yaml
```
Expected: error `table identifier not fully qualified (catalog.schema.table): not_qualified` and `exit=1`.

- [ ] **Step 4: Commit**

```bash
git add genie/build_space.py
git commit -m "feat(genie): add config loader that emits create_or_update args"
```

---

### Task 3: Create, curate, and export the space (orchestrator: MCP + UI)

**Files:**
- Create: `genie/hotel_booking_space.serialized.json` (written from the export payload)

**Interfaces:**
- Consumes: the `create_or_update` args from `python genie/build_space.py`, and the `instructions` + `curated_sql` from `genie/hotel_booking_space.yaml`.
- Produces: a live Genie space (record its `space_id` and resolved `warehouse_id`), and the committed serialized lockfile whose config includes both tables, the general instructions, and the three curated SQL examples.

- [ ] **Step 1: Create/update the space**

Run `python3 genie/build_space.py` to get the args, then call the `manage_genie` MCP tool with `action="create_or_update"` and those args (`display_name`, `table_identifiers`, `description`, `sample_questions`; include `warehouse_id` only if the config sets one — otherwise let it auto-detect). Record the returned `space_id`, `warehouse_id`, and `table_count` (expect `table_count == 2`).

- [ ] **Step 2: Verify the baseline space**

Call `manage_genie` with `action="get"`, `space_id=<from step 1>`. Expected: `display_name` = "Hotel Booking Cancellation Intelligence", `table_identifiers` = the two tables, `sample_questions` = the six from the config.

- [ ] **Step 3: Add general instructions + curated SQL in the Genie UI**

Open the space in the Genie UI (`https://fevm-fe-bar-ecastillo.cloud.databricks.com` → Genie → the space). Paste the config's `instructions` block into the space's **General instructions**, and add each `curated_sql` entry as an **example SQL query** (use the `title` as the description and the `sql` as the query). Save.

- [ ] **Step 4: Export the full config to the lockfile**

Call `manage_genie` with `action="export"`, `space_id=<...>`. Write the returned `serialized_space` (pretty-printed if it is JSON, otherwise verbatim) to `genie/hotel_booking_space.serialized.json`.

- [ ] **Step 5: Verify the lockfile captured the curation**

Run:
```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && python3 -c "
data = open('genie/hotel_booking_space.serialized.json').read()
assert 'gold_hotel_month' in data and 'reservation_risk' in data, 'tables missing'
assert 'HONEST LIMITS' in data, 'instructions not captured'
assert 'est_lost_revenue' in data, 'curated SQL not captured'
print('serialized lockfile OK, bytes=%d' % len(data))
"
```
Expected: `serialized lockfile OK, bytes=<n>`

- [ ] **Step 6: Commit**

```bash
git add genie/hotel_booking_space.serialized.json
git commit -m "feat(genie): create curated space and commit serialized lockfile"
```

---

### Task 4: Verify via `ask_genie` and write the evidence doc (orchestrator)

**Files:**
- Create: `docs/evidence/genie-space-run.md`

**Interfaces:**
- Consumes: the live `space_id` (Task 3), the six sample questions (Task 1).
- Produces: `docs/evidence/genie-space-run.md` with, per question, the generated SQL + returned columns/rows, plus one numeric spot-check against `execute_sql`, plus recorded metadata.

- [ ] **Step 1: Ask each sample question**

For each of the six `sample_questions`, call the `ask_genie` MCP tool with `space_id=<...>` and `question=<the question>`. Capture `question`, `sql`, `columns`, `data` (or `row_count`), and `status` for each. If a question returns no SQL or an obviously wrong result, refine the space's general instructions (Task 3, Step 3), re-export (Task 3, Step 4), and re-ask; document the fix rather than hiding it.

- [ ] **Step 2: Spot-check one numeric answer with direct SQL**

Call `execute_sql` with:
```sql
SELECT risk_band, count(*) AS reservations,
       round(avg(cancel_probability), 4) AS avg_cancel_probability
FROM fe_bar_ecastillo_catalog.hotel_booking_dev.reservation_risk
GROUP BY risk_band
ORDER BY avg_cancel_probability DESC
```
Confirm the numbers match the `ask_genie` answer to "What's the average cancel probability by risk band?".

- [ ] **Step 3: Write the evidence doc**

Create `docs/evidence/genie-space-run.md` using this structure, filling every bracketed field from the actual runs:

```markdown
# Evidence — Genie space "Hotel Booking Cancellation Intelligence"

**Workspace:** fevm-fe-bar-ecastillo
**Catalog/schema:** fe_bar_ecastillo_catalog.hotel_booking_dev
**space_id:** [recorded]
**warehouse_id:** [recorded]
**Tables:** gold_hotel_month, reservation_risk
**Risk model_version observed:** [from a risk answer]
**Run date:** 2026-09-29

## Sample question runs

### Q1: What was the cancellation rate for City Hotel by month in 2016?
- Generated SQL:
  ```sql
  [sql]
  ```
- Result (columns + rows):
  [rows or row_count]

### Q2: Which arrival month had the highest estimated lost revenue?
[...same structure...]

### Q3: How many reservations are high risk per hotel?
[...]

### Q4: What's the average cancel probability by risk band?
[...]

### Q5: Compare the cancellation rate between the two hotels.
[...]

### Q6: What model version produced the current risk scores?
[...]

## Spot-check (ask_genie vs direct SQL)

Direct `execute_sql` for risk-band distribution:
[rows]

Matches the Q4 ask_genie answer: [yes/no + note]
```

- [ ] **Step 4: Verify the evidence doc has no unfilled placeholders**

Run:
```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && ! grep -nE "\[recorded\]|\[sql\]|\[rows or row_count\]|\.\.\.same structure|\[\.\.\.\]|\[from a risk answer\]" docs/evidence/genie-space-run.md && echo "evidence doc filled"
```
Expected: `evidence doc filled`

- [ ] **Step 5: Commit**

```bash
git add docs/evidence/genie-space-run.md
git commit -m "docs(genie): add ask_genie verification evidence"
```

---

### Task 5: README — document the Genie slice

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: `space_id` and metadata from Tasks 3–4.
- Produces: a Genie section documenting the space, its tables, how to rebuild/query, and the committed artifacts; checks the Genie deliverable box.

- [ ] **Step 1: Add a Genie section to the README**

Add a "Genie — natural-language analytics" subsection near the existing Lakebase documentation. Include:
- The space name + `space_id`, workspace, and the two tables it exposes.
- Artifacts: `genie/hotel_booking_space.yaml` (source of truth), `genie/hotel_booking_space.serialized.json` (export lockfile), `genie/build_space.py` (loader), `docs/evidence/genie-space-run.md` (verification).
- Rebuild steps: `python genie/build_space.py` → `manage_genie create_or_update` → add instructions/curated SQL in the UI → `manage_genie export` → commit; note that Genie is not a bundle resource.
- Query: `ask_genie(space_id=..., question=...)`, or re-import elsewhere via `manage_genie import` with the serialized lockfile (catalog remap for prod).
- A one-line honest limit: no occupancy/RevPAR (inventory not in data); `reservation_risk` has no date so risk answers are aggregate/hotel-level.

- [ ] **Step 2: Check the Genie deliverable box**

In the Deliverables checklist, update the build line so the Genie room is marked done (e.g., `The build (code, notebooks with outputs, app, Genie room)` — note Genie complete), consistent with how prior slices were marked.

- [ ] **Step 3: Verify the README references the real space_id**

Run:
```bash
cd /Users/esteban.castillo/Documents/Projects/fe-bar-fy27 && grep -n "hotel_booking_space.serialized.json" README.md && grep -niE "space_id" README.md && echo "README updated"
```
Expected: matching lines + `README updated`.

- [ ] **Step 4: Commit and push**

```bash
git add README.md
git commit -m "docs(genie): document Genie NL analytics slice in README"
git push origin main
```
(Push requires the `jestebanc16` gh account and `required_permissions=["full_network","git_write"]` + smart-mode approval, per repo convention.)

---

## Self-review notes

- **Spec coverage:** purpose/two question families → Tasks 1,4; two-table scope → Task 1 + Global Constraints; config-as-source + serialized lockfile (Approach A) → Tasks 1,2,3; full curation (description + instructions + curated SQL + sample questions) → Task 1 authored, Task 3 applied/exported; idempotent create → Task 3; ask_genie evidence + numeric spot-check → Task 4; README → Task 5; honest limits/out-of-scope → embedded in Task 1 instructions and Task 5. No prod space / dashboards / agent wiring — excluded, matching the spec.
- **Tool-reality gap handled:** instructions + curated SQL are UI-applied then export-captured (Global Constraints + Task 3), because `manage_genie create_or_update` does not expose them.
- **Type/name consistency:** `load_config`/`create_or_update_args` defined in Task 2 and consumed in Task 3; `space_id`/`warehouse_id` produced in Task 3 and consumed in Tasks 4–5; the six sample questions and three curated SQL titles are defined once in Task 1 and referenced by name thereafter.
