# Numbers sheet — Meridian cancellation-intelligence deck

Use these figures exactly. Sources are the committed evidence docs under
`docs/evidence/` and live queries against
`fe_bar_ecastillo_catalog.hotel_booking_dev` on workspace
`fevm-fe-bar-ecastillo` (2026-11-10).

## Company framing

| Field | Value |
|-------|-------|
| Company | Meridian Hotels & Resorts (fictional) |
| Properties in data | City Hotel, Resort Hotel |
| Dataset | Public Hotel Booking Demand (Antonio, Almeida & Nunes) |

## Portfolio outcome (`gold_hotel_month`)

| Metric | Value |
|--------|------:|
| Bookings (silver / scored) | 119,389 |
| Cancellations | 44,224 |
| Overall cancel rate | 37.04% |
| Estimated lost room-night revenue (total) | $16,727,237 |
| Arrival-month coverage | 52 hotel×month rows (2015–2017) |

### By hotel

| Hotel | Bookings | Cancel rate | Est. lost revenue |
|-------|---------:|------------:|------------------:|
| City Hotel | 79,330 | 41.73% | $10,885,060 |
| Resort Hotel | 40,059 | 27.76% | $5,842,177 |

### Peak month

| Metric | Value |
|--------|-------|
| Highest est. lost revenue month | City Hotel, May 2017 |
| Est. lost revenue that month | ~$878,912 |

### City Hotel monthly cancel rates (2016 sample for trend chart)

Average of the 12 monthly 2016 rates below: **39.8%** (0.3979). Label the chart
"2016 avg 39.8%". Do not use 41.7% for this chart; 41.7% is City Hotel's all-years rate.

| Month | Cancel rate |
|------:|------------:|
| Jan | 0.3211 |
| Feb | 0.3922 |
| Mar | 0.3638 |
| Apr | 0.4322 |
| May | 0.3906 |
| Jun | 0.4384 |
| Jul | 0.3331 |
| Aug | 0.3692 |
| Sep | 0.4048 |
| Oct | 0.4615 |
| Nov | 0.4356 |
| Dec | 0.4326 |

**Definition:** `est_lost_revenue = adr × stay_nights` when canceled, else 0.
This is a **room-night proxy**, not RevPAR. RevPAR / occupancy need room
inventory, which the dataset does not contain.

## Model (`hotel_cancel_classifier` v1 @champion)

| Metric | Value |
|--------|------:|
| Estimator | HistGradientBoostingClassifier (sklearn Pipeline) |
| Split | Temporal — latest ~20% of arrivals held out |
| ROC-AUC | 0.8384 (~0.84) |
| PR-AUC | 0.8083 (~0.81) |
| Precision | 0.757 (~0.76) |
| Recall | 0.6016 (~0.60) |
| F1 | 0.6704 (~0.67) |

## Risk triage (`reservation_risk`, all scored rows)

| Risk band | Rule | Reservations | Share | Avg cancel probability |
|-----------|------|-------------:|------:|-----------------------:|
| High | p ≥ 0.70 | 26,814 | ~22.5% | 0.9186 |
| Medium | 0.40 ≤ p < 0.70 | 14,281 | ~12.0% | 0.5374 |
| Low | p < 0.40 | 78,294 | ~65.6% | 0.1498 |
| **Total** | | **119,389** | 100% | |

## App serving layer (Lakebase)

| Metric | Value |
|--------|------:|
| Synced distinct reservations served to the app | 87,395 |
| App KPI total (served snapshot) | 87,395 |
| App KPI high-risk | 10,238 |
| App KPI avg cancel probability | 0.2793 (27.9%) |

Note: the app serves a **deduped** snapshot (`reservation_id` content-hash
dedupe), so its KPI totals (87,395 / 10,238) are lower than the full
`reservation_risk` table (119,389 / 26,814). Prefer the full-table risk
counts for the “actionable set” story; use the app KPIs when describing
the live product UI.

## Product / platform one-liners

- **App URL (dev):** https://hotel-revenue-app-7474655249991979.aws.databricksapps.com
- **Actions supported:** reconfirmed, deposit_requested, overbooked_backup, released, note
- **Governance:** PII column masks (`country` / `agent` / `company`), per-property row filters, classification tags, lineage
- **Genie space:** “Hotel Booking Cancellation Intelligence” over `gold_hotel_month` + `reservation_risk`

## Do not claim

- Measured RevPAR lift
- Occupancy % improvement
- Overbooking accuracy / walk-out rate
- Any dollar “recovered” figure from the app (pilot not yet run)
