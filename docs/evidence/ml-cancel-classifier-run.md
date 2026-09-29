# Evidence: cancellation-probability ML slice (dev)

Trained, registered, batch-scored, and served the cancellation classifier on the
`serverless_stable_eojwo0_catalog.hotel_booking_dev` schema.

Train and scoring are now a single chained job `hotel_cancel_ml` (`train` -> `score`); a
single `databricks bundle run hotel_cancel_ml -t dev` performs the full refresh. The
per-task results below were captured from that job (originally the two standalone jobs
`hotel_cancel_train` / `hotel_cancel_score`, since consolidated).

## 1. Train (`hotel_cancel_ml` task `train`)

```bash
databricks bundle run hotel_cancel_ml -t dev -p serverless_stable_eojwo0
```

`TERMINATED SUCCESS`. Notebook exit summary:

```json
{
  "model": "serverless_stable_eojwo0_catalog.hotel_booking_dev.hotel_cancel_classifier",
  "version": 1,
  "run_id": "7cf89cf0465d4687a4f0e4b50376c1ac",
  "roc_auc": 0.8384,
  "pr_auc": 0.8083,
  "precision": 0.757,
  "recall": 0.6016,
  "f1": 0.6704
}
```

- Estimator: sklearn `Pipeline(ColumnTransformer(OneHot + numeric passthrough),
  HistGradientBoostingClassifier)`.
- **Temporal** holdout (train earliest ~80% of arrivals, test latest ~20%) - a deliberately
  harder, honest split than a random shuffle, so ROC-AUC ~0.84 reflects true forward-looking
  performance rather than an inflated in-distribution score.
- MLflow run logs ROC-AUC / PR-AUC / precision / recall / F1 plus artifacts
  `confusion_matrix.png`, `roc_pr_curves.png`, `feature_importance.png`.
- Registered to UC `hotel_cancel_classifier` v1 and aliased `@champion`.

## 2. Batch score (`hotel_cancel_ml` task `score`, depends on `train`)

```bash
# Runs automatically after `train` succeeds within hotel_cancel_ml.
databricks bundle run hotel_cancel_ml -t dev -p serverless_stable_eojwo0
```

`TERMINATED SUCCESS`. Notebook exit: `{"target": "...reservation_risk", "rows": 119389,
"model_version": 1}` - one scored row per reservation, matching `silver_bookings`.

Risk-band distribution of `reservation_risk`:

| risk_band | reservations | avg cancel_probability |
|-----------|-------------:|-----------------------:|
| high (p >= 0.7)   | 26,814 | 0.9186 |
| medium (p >= 0.4) | 14,281 | 0.5374 |
| low               | 78,294 | 0.1498 |

~22% of bookings land in the high-risk band - the actionable set for deposit / overbooking /
re-confirmation workflows downstream.

## 3. Serve (real-time endpoint)

Endpoint `hotel-cancel-classifier` (dev-prefixed `dev_esteban_castillo_hotel-cancel-classifier`)
serving `hotel_cancel_classifier` v1, scale-to-zero. State: `{"ready": "READY"}`.

Sample query (two reservations) and response:

```bash
databricks serving-endpoints query dev_esteban_castillo_hotel-cancel-classifier \
  --json @sample_payload.json -p serverless_stable_eojwo0
# payload: [ high-lead-time booking w/ prior cancellation ,  repeated guest w/ parking + 3 requests ]
```

```json
{ "predictions": [ 1, 0 ] }
```

The long-lead-time booking with a previous cancellation is predicted to cancel; the loyal,
short-lead-time guest is predicted to keep. The pyfunc endpoint returns the class label;
per-reservation probabilities live in the `reservation_risk` table (loaded via the sklearn
flavor's `predict_proba` in the batch job).

## Deployment note (terraform state drift)

The serving endpoint is deployed from `resources/hotel_cancel_serving.yml`. The first apply
provisioned the endpoint but an intermittent workspace **IP ACL block hit the terraform
state file** (`.../state/terraform.tfstate`) during the final state-update step, so the
endpoint exists in the workspace but was not recorded in bundle state. A subsequent
`bundle deploy` therefore reports `Endpoint ... already exists`. To reconcile in a
stable-network session: delete the existing endpoint once, then redeploy -

```bash
V=$(databricks model-versions get-by-alias \
      serverless_stable_eojwo0_catalog.hotel_booking_dev.hotel_cancel_classifier champion \
      -p serverless_stable_eojwo0 -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["version"])')
databricks serving-endpoints delete dev_esteban_castillo_hotel-cancel-classifier -p serverless_stable_eojwo0
databricks bundle deploy -t dev -p serverless_stable_eojwo0 --var="cancel_model_version=$V"
```

This is an environmental artifact (the ACL flap), not a bundle-config issue; the endpoint
itself is READY and serving.

## Workspace migration (fevm-fe-bar-ecastillo)

The full stack was re-deployed to a new workspace
`https://fevm-fe-bar-ecastillo.cloud.databricks.com` on
`fe_bar_ecastillo_catalog.hotel_booking_dev` (profile `fevm-fe-bar-ecastillo`). This was a
clean deploy - no terraform state drift this time - so the reconcile steps above did not
apply.

- **Ingest**: `hotel_booking_ingest_etl` re-run - bronze 119,390 / silver 119,389 / gold 52.
- **Governance**: `hotel_booking_governance` re-run - 38 OK / 36 expected FAIL (11 gold-MV
  column comments `EXPECT_TABLE_NOT_VIEW`, 25 grants `PRINCIPAL_DOES_NOT_EXIST`).
- **ML** (`hotel_cancel_ml`, `TERMINATED SUCCESS`):
  - `train`: `hotel_cancel_classifier` v1 `@champion`, ROC-AUC 0.8384, PR-AUC 0.8083,
    precision 0.757, recall 0.6016, F1 0.6704 (`run_id 2856fa95239d4b6091ef83a26d2271ff`).
  - `score`: `reservation_risk` 119,389 rows, `model_version 1`.
- **Serve**: `dev_esteban_castillo_hotel-cancel-classifier` deployed with
  `--var cancel_model_version=1`, `{"ready": "READY"}`. Sample query returns
  `{"predictions": [0]}` for a low-risk transient booking. The signature expects the derived
  features `arrival_year` and `stay_nights` (not the raw `arrival_date_*` columns).
