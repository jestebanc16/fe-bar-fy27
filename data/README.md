# Data landing — Hotel Booking Demand

The raw dataset is **not committed** to this repo (Kaggle license + ~10 MB / 119K rows).
Download it, then land it in the Unity Catalog Volume the Lakeflow pipeline reads from.

## Source

[Hotel Booking Demand](https://www.kaggle.com/datasets/jessemostipak/hotel-booking-demand)
— `hotel_bookings.csv`, ~119,390 rows x 32 columns, bookings from July 2015 to
August 2017 for one city hotel and one resort hotel. Public, anonymized (no guest
names; `agent` / `company` are numeric IDs).

## 1. Download the CSV

Option A — Kaggle CLI (needs `~/.kaggle/kaggle.json` API token):

```bash
pip install kaggle
kaggle datasets download -d jessemostipak/hotel-booking-demand -p data/ --unzip
# -> data/hotel_bookings.csv
```

Option B — download `hotel_bookings.csv` manually from the dataset page and place it
at `data/hotel_bookings.csv`.

## 2. Land it in the UC Volume

The pipeline reads from `/Volumes/{catalog}/{schema}/raw/hotel_bookings/`. Create the
volume once, then copy the file in. Replace `{catalog}` / `{schema}` / `{profile}` with
the values you deploy the bundle to (see `databricks.yml`).

```bash
# Create the raw volume (idempotent-ish; ignore "already exists")
databricks volumes create {catalog} {schema} raw MANAGED --profile {profile}

# Copy the CSV into the Auto Loader source path
databricks fs cp data/hotel_bookings.csv \
  dbfs:/Volumes/{catalog}/{schema}/raw/hotel_bookings/hotel_bookings.csv \
  --profile {profile}

# Verify
databricks fs ls dbfs:/Volumes/{catalog}/{schema}/raw/hotel_bookings/ --profile {profile}
```

Auto Loader picks up any new file dropped in that folder on the next pipeline run, so
re-landing the same file will not double-count (managed checkpoint).

## .gitignore

`data/*.csv` and `data/*.zip` are git-ignored so the raw dataset never gets committed.
