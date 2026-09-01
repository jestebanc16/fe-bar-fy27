# Unity Catalog governance for hotel booking demand - design

Status: implemented 2026-09-01. Second slice of the end-to-end build (Govern), on top of
the Lakeflow ingest medallion. Target: `serverless_stable_eojwo0_catalog.hotel_booking_dev`.

## Goal

A version-controlled Unity Catalog governance layer over the medallion: personas + grants,
dynamic column masking, per-property row-level security, a column-level data dictionary,
classification/layer tags, informational keys, and committed lineage/masking evidence.

## Approach

Governance is authored as idempotent SQL in `governance/` plus `governance/apply.sh`,
because Lakeflow SDP cannot express grants, masks, tags, or row filters. The apply script
substitutes `{catalog}`/`{schema}`, creates persona groups, adds the operator to
`hotel_engineer`, probes the membership function, and runs each SQL file one statement at a
time (continue-on-error with a summary). It can be re-applied after any pipeline change.

## Pipeline change

`silver_bookings` gained a deterministic content-hash surrogate `reservation_id` (streaming
-safe `sha2`; `monotonically_increasing_id()` is not allowed on streaming DataFrames), and
`agent`/`company` are cast to STRING so the `mask_pii(STRING)` mask type-matches. Redeployed
with a full-refresh run.

## Personas and access model

Groups: `hotel_engineer` (full, unmasked, all rows), `hotel_analyst` (masked PII, all rows),
`hotel_mgr_city` / `hotel_mgr_resort` (masked PII, row-filtered to their property).

- `mask_pii(v)`: `country`, `agent`, `company` return clear text only for `hotel_engineer`,
  else `'***'`.
- `hotel_row_filter(h)`: engineers + analysts see all; each manager group is scoped to its
  hotel. A principal in no group sees zero rows.

## Files

- `governance/functions.sql` - mask + row-filter UDFs (membership function injected).
- `governance/comments.sql` - table + silver column data dictionary.
- `governance/tags.sql` - `hb_data_class` (pii/financial) + `layer`/`certified`.
- `governance/policies.sql` - idempotent (drop-then-set) column masks + row filter.
- `governance/grants.sql` - persona grant matrix + function EXECUTE (production pattern).
- `governance/constraints.sql` - reference DDL only (see limitations).
- `governance/apply.sh` - orchestrates groups, membership, substitution, execution.

## Environment limitations (documented, not blockers)

1. UC object grants need account-level groups; this workspace has no account-admin, so
   `grants.sql` is delivered as the production pattern. Data protection (masks + row filter)
   does not depend on grants and is enforced.
2. `gold_hotel_month` is a materialized view: rejects `ALTER COLUMN` (comments/tags) and
   `SET ROW FILTER`. Gold keeps table-level comment + tags; managers are enforced on silver.
3. SDP-managed streaming tables / MVs reject external constraint DDL, so PK/NOT NULL are
   documented via the data dictionary rather than declared. Not-null on `hotel` is enforced
   at ingest by the pipeline expectation.
4. Databricks SQL caches group membership for minutes, so single-session live membership
   flips are unreliable for demoing masked-with-rows output; enforcement is verified via
   `information_schema` and the engineer-unmasked vs no-group-deny contrast.

## Evidence

`docs/evidence/unity-catalog-governance.md`: column_masks, row_filters, routines, column/
table tags, data dictionary, lineage, and the live engineer-unmasked / no-access contrast.

## Out of scope (later slices)

Lakebase serving, ML/model registry governance, Genie, the App. No Delta Sharing, no
attribute-based access beyond the three PII columns, no external locations.
