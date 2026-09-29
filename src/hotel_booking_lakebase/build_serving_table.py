# Databricks notebook source
# MAGIC %md
# MAGIC # Build `reservation_risk_serving` (denormalized Delta serving source)
# MAGIC
# MAGIC Joins `reservation_risk` (scores) with selected `silver_bookings` detail into one
# MAGIC row per reservation. This Delta table is the source the Lakebase synced table mirrors
# MAGIC into Postgres. Deduped on `reservation_id` so the synced-table primary key is valid
# MAGIC (the content-hash key is shared by exact-duplicate bookings by design).

# COMMAND ----------

dbutils.widgets.text("catalog", "", "Unity Catalog catalog")
dbutils.widgets.text("schema", "", "Schema holding reservation_risk / silver_bookings")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
assert CATALOG and SCHEMA, "catalog and schema parameters are required"

TARGET = f"{CATALOG}.{SCHEMA}.reservation_risk_serving"

# COMMAND ----------

from pyspark.sql import functions as F

risk = spark.table(f"{CATALOG}.{SCHEMA}.reservation_risk")
book = spark.table(f"{CATALOG}.{SCHEMA}.silver_bookings").select(
    "reservation_id",
    "arrival_date",
    "lead_time",
    "adr",
    "market_segment",
    "adults",
    "children",
    "babies",
    "deposit_type",
    "customer_type",
)

serving = (
    risk.alias("r")
    .join(book.alias("b"), on="reservation_id", how="left")
    .select(
        F.col("reservation_id"),
        F.col("r.hotel").alias("hotel"),
        F.col("b.arrival_date").alias("arrival_date"),
        F.col("b.lead_time").alias("lead_time"),
        F.col("b.adr").alias("adr"),
        F.col("b.market_segment").alias("market_segment"),
        F.col("b.adults").alias("adults"),
        F.col("b.children").alias("children"),
        F.col("b.babies").alias("babies"),
        F.col("b.deposit_type").alias("deposit_type"),
        F.col("b.customer_type").alias("customer_type"),
        F.col("r.cancel_probability").alias("cancel_probability"),
        F.col("r.risk_band").alias("risk_band"),
        F.col("r.model_version").alias("model_version"),
        F.col("r.scored_at").alias("scored_at"),
    )
    .dropDuplicates(["reservation_id"])
)

(
    serving.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(TARGET)
)

spark.sql(
    f"ALTER TABLE {TARGET} ALTER COLUMN reservation_id SET NOT NULL"
)
spark.sql(
    f"COMMENT ON TABLE {TARGET} IS "
    "'Denormalized per-reservation risk + booking detail. Source for the Lakebase synced "
    "table reservation_risk_serving_synced.'"
)

# COMMAND ----------

rows = spark.table(TARGET).count()
print(f"{TARGET}: {rows:,} rows")

dbutils.notebook.exit(__import__("json").dumps({"target": TARGET, "rows": rows}))
