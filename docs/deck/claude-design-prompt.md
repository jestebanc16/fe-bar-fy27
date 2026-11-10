# Claude Design prompt — Meridian cancellation-intelligence deck

Paste the block below into Claude Design. Attach the three PNGs from
`docs/deck/assets/` and the numbers sheet `docs/deck/numbers.md`.

---

Create a 16:9 executive presentation deck (about 11 slides plus one appendix slide) for Meridian Hotels & Resorts, a fictional hotel company. The deck shows how Meridian's revenue managers can see which bookings are likely to cancel and act on them before rooms go unsold.

AUDIENCE AND TONE
- Primary audience: executive sponsor (revenue / GM). Secondary: revenue managers who will use the app.
- Lead with the business outcome and money at risk. Then show how it works, then the tool, then limits.
- Plain, confident, data-led. No hype, no emojis, no marketing fluff. Every number needs a source label.

VISUAL DIRECTION
- Match the app's look: slate neutrals, indigo-600 accent, and risk colors red (high), amber (medium), green (low).
- Clean layout with generous whitespace. Large KPI numbers, simple charts, one idea per slide.
- Use the attached screenshots as real product visuals, not mockups.
- Provide both a light theme and a dark theme variant of the palette.
- Attachments:
  - `app-list-light.png` — revenue-manager list view (light)
  - `app-list-dark.png` — same view (dark)
  - `app-detail-action.png` — reservation detail drawer with write-back form and prior actions
  - `numbers.md` — exact figures to use (do not invent alternatives)

DATA (use exactly the numbers in the attached numbers sheet)
Business outcome
- 119,389 bookings across two hotels (City Hotel, Resort Hotel), arrival months 2015 to 2017 (52 months).
- Overall cancellation rate: 37.0% (44,224 of 119,389 bookings canceled).
- City Hotel: 79,330 bookings, 41.7% cancel rate, about $10.9M estimated lost room-night revenue.
- Resort Hotel: 40,059 bookings, 27.8% cancel rate, about $5.8M estimated lost room-night revenue.
- Total estimated lost room-night revenue: about $16.7M.
- Highest single month: City Hotel, May 2017, about $879K estimated lost revenue.
- Lost revenue is ADR × canceled room-nights. It is an estimate and a room-night proxy, not RevPAR.

Model (cancellation-probability classifier)
- Gradient-boosted classifier trained on a temporal split (the latest ~20% of arrivals held out for test).
- ROC-AUC 0.84, PR-AUC 0.81, precision 0.76, recall 0.60, F1 0.67.

Risk triage (all scored reservations)
- High risk (p ≥ 0.70): 26,814 reservations (~22%), average cancel probability 0.92.
- Medium risk (p 0.40–0.70): 14,281 reservations, average 0.54.
- Low risk: 78,294 reservations, average 0.15.

Platform
- Lakehouse pipeline: bronze → silver → gold tables in Unity Catalog, with lineage.
- Governance: column masks on PII (country, agent, company), per-property row-level security, classification tags.
- Serving: Lakebase (managed Postgres) serves 87,395 distinct scored reservations to the app.
- Databricks App for revenue managers: KPI header, risk filters, reservation detail, and recorded actions (reconfirm, deposit requested, overbooking backup, release, note). Every action is stored with the user's identity as an audit trail.
- Genie natural-language analytics over the same data.

SLIDE OUTLINE
1. Title: "Meridian Hotels & Resorts: Acting on Booking Cancellations Before Rooms Go Unsold". Subtitle: Revenue Management Cancellation Intelligence on Databricks. Mark the company as fictional in small print.
2. The headline: $16.7M in estimated room revenue lost to cancellations across two hotels, with a 37% cancellation rate. Show the three numbers large.
3. Where it is lost: City Hotel vs Resort Hotel comparison (cancel rate and lost revenue). Include a monthly trend chart of cancel rate for City Hotel (use the sample monthly rates from the numbers sheet).
4. The decision problem: which bookings will cancel, and what to do about them (deposit requests, controlled overbooking, reconfirmation nudges). Frame the question for revenue managers.
5. How it works: pipeline diagram (bronze → silver → gold → classifier → scores in Lakebase → app and Genie on top). Keep it simple.
6. How good the model is: the metrics above. Explain the temporal split in one sentence so executives trust it. Show a simple precision/recall tradeoff visual.
7. Risk triage: the 26,814 high-risk reservations (~22%) as the actionable set. Show the three risk bands as a stacked bar.
8. The revenue manager's view: use `app-list-light.png`. Callouts: KPI header, risk filters, sorted at-risk list.
9. Taking action: use `app-detail-action.png`. Callouts: reservation detail, recorded action, prior-action audit trail.
10. Governed by design: PII masking, per-property access, lineage, audit trail. Short bullets.
11. Quantified exposure today, measured recovery next. Full copy and rules are in the REVISION: SLIDE 11 section at the end of this prompt.
12. Appendix: Methodology and sources. List the data source (public Hotel Booking Demand dataset), the definition of estimated lost revenue, the model split, and that evidence lives under `docs/evidence/` in the project repo.

HONESTY RULES
- Do not state RevPAR, occupancy, or overbooking-accuracy results. They are not measured.
- Label "estimated lost revenue" as an estimate everywhere it appears.
- Note that the source dataset is public, real bookings from two hotels, and that the Meridian company framing is fictional.

OUTPUT
- Deliver the deck with speaker notes for each slide (2–4 sentences each).
- Prefer the light screenshot on slide 8 and the detail drawer on slide 9; keep the dark screenshot available as an alternate product visual.

---

REVISION: SLIDE 11

Revise slide 11 of the 12-slide Meridian cancellation deck. Change slide 11 only. Keep the other 11 slides, the palette, fonts, and layout system unchanged.

Context: Meridian Hotels & Resorts is a fictional company. The data is the public Hotel Booking Demand dataset (City Hotel and Resort Hotel). Reframe slide 11 as: quantified exposure today, measured recovery next.

Slide 11 title (use exactly):
"$16.7M is the exposure we can quantify today. Recovery is what the pilot measures."

Section 1, "Quantified now (estimated, from data)":
- $16.7M estimated lost room-night revenue across two hotels: City Hotel $10.9M, Resort Hotel $5.8M.
- 26,814 high-risk reservations (~22.5% of 119,389 bookings) form the actionable set.
- Label the method: est. lost revenue = ADR × stay nights, for canceled bookings. This is a room-night proxy, not RevPAR.

Section 2, "Illustrative sensitivity (arithmetic, not a result)":
- Each 1% of the $16.7M recovered is about $167K.
- 5% is about $836K. 10% is about $1.67M.
- Must carry the label "illustrative" and must not be presented as a forecast or result.

Section 3, "Pilot will measure":
- Recovered rooms and avoided lost revenue at one property.
- Overbooking accuracy: rooms recovered without walk-outs.

Section 4, "Not measurable with this dataset":
- RevPAR and occupancy impact. Both need room inventory data, which this dataset does not include.

Footer line: "Next: pilot at one property, measure recovery, then add room inventory for RevPAR and occupancy."

Rules:
- Do not claim measured RevPAR lift, occupancy improvement, overbooking accuracy, or any recovered dollar figure from the app. The pilot has not run.
- Keep the slide honest and specific. No marketing language.
- Keep the existing slide-number and footer treatment.
- Return the revised slide 11 only, with the same visual style as slides 1–10.
- Speaker notes for slide 11: 2–4 sentences, using the same honesty rules.

---

REVISION: SLIDE 3

Revise slide 3 only. Keep the other slides, palette, fonts, and layout unchanged.

Fix the chart label. The monthly line chart shows City Hotel's 2016 monthly cancel rates
(sample values in numbers.md). The current label "City Hotel cancel rate by month, 2016 · avg 41.7%" is wrong.

Use exactly this label for the chart header:
"City Hotel cancel rate by month, 2016 · avg 39.8%"

Rules:
- 39.8% is the average of the 12 monthly 2016 rates. Do not use 41.7%, which is City Hotel's all-years cancel rate and belongs on slide 3's per-hotel comparison only.
- Keep the other slide 3 text unchanged: City Hotel 79,330 bookings, $10.9M, 41.7% cancel rate; Resort Hotel 40,059 bookings, $5.8M, 27.8% cancel rate; peak month note; source line.
- Return the revised slide 3 only, with the same visual style as slides 1–12.
