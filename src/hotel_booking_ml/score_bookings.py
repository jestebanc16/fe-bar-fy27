# Databricks notebook source
# MAGIC %md
# MAGIC # Batch-score bookings -> `reservation_risk`
# MAGIC
# MAGIC Loads the `@champion` cancellation classifier from Unity Catalog and scores every
# MAGIC reservation in `silver_bookings`, writing per-reservation risk to
# MAGIC `{catalog}.{schema}.reservation_risk` - the table the later Lakebase + app stages read.
# MAGIC
# MAGIC The feature columns are derived from the model's own input signature, so scoring stays
# MAGIC in lock-step with training. Probabilities come from `predict_proba`, so we load the
# MAGIC sklearn flavor directly (pyfunc/`spark_udf` returns the class label, not the score).
# MAGIC At ~119K rows, driver-side scoring is trivial; for much larger data a model-broadcast
# MAGIC `pandas_udf` would scale this across executors.

# COMMAND ----------

dbutils.widgets.text("catalog", "", "Unity Catalog catalog")
dbutils.widgets.text("schema", "", "Schema holding silver_bookings")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
assert CATALOG and SCHEMA, "catalog and schema parameters are required"

MODEL_NAME = f"{CATALOG}.{SCHEMA}.hotel_cancel_classifier"
MODEL_URI = f"models:/{MODEL_NAME}@champion"
TARGET = f"{CATALOG}.{SCHEMA}.reservation_risk"
print(f"Model : {MODEL_URI}")
print(f"Target: {TARGET}")

# COMMAND ----------

import mlflow
import mlflow.sklearn
from mlflow.models import get_model_info
from mlflow.tracking import MlflowClient
from pyspark.sql import functions as F

mlflow.set_registry_uri("databricks-uc")

# Resolve the concrete champion version (recorded on each scored row for lineage).
client = MlflowClient()
model_version = int(client.get_model_version_by_alias(MODEL_NAME, "champion").version)
print(f"champion = v{model_version}")

# Feature names (and order) straight from the model signature. Categorical membership
# mirrors training (train_cancel_classifier.py CATEGORICAL) rather than parsing the
# signature's DataType repr, which is brittle across MLflow versions.
CATEGORICAL = {
    "hotel",
    "meal",
    "market_segment",
    "distribution_channel",
    "reserved_room_type",
    "deposit_type",
    "customer_type",
}
info = get_model_info(MODEL_URI)
feature_cols = [c.name for c in info.signature.inputs.inputs]
string_cols = {c for c in feature_cols if c in CATEGORICAL}
print(f"{len(feature_cols)} feature columns; {len(string_cols)} categorical")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assemble features (same fill rules as training) and score

# COMMAND ----------

sdf = spark.table(f"{CATALOG}.{SCHEMA}.silver_bookings")

select_exprs = [F.col("reservation_id"), F.col("hotel").alias("_hotel")]
for name in feature_cols:
    if name in string_cols:
        select_exprs.append(
            F.coalesce(F.col(name).cast("string"), F.lit("missing")).alias(name)
        )
    else:
        select_exprs.append(
            F.coalesce(F.col(name).cast("double"), F.lit(0.0)).alias(name)
        )

pdf = sdf.select(*select_exprs).toPandas()
print(f"Scoring {len(pdf):,} reservations")

model = mlflow.sklearn.load_model(MODEL_URI)
pdf["cancel_probability"] = model.predict_proba(pdf[feature_cols])[:, 1]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write `reservation_risk`

# COMMAND ----------

out = pdf[["reservation_id", "_hotel", "cancel_probability"]].rename(
    columns={"_hotel": "hotel"}
)
risk = (
    spark.createDataFrame(out)
    .withColumn(
        "risk_band",
        F.when(F.col("cancel_probability") >= 0.7, F.lit("high"))
        .when(F.col("cancel_probability") >= 0.4, F.lit("medium"))
        .otherwise(F.lit("low")),
    )
    .withColumn("model_version", F.lit(model_version))
    .withColumn("scored_at", F.current_timestamp())
)

(
    risk.write.format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(TARGET)
)

spark.sql(
    f"COMMENT ON TABLE {TARGET} IS "
    "'Per-reservation cancellation risk scored by hotel_cancel_classifier@champion. "
    "Source for Lakebase serving + the revenue-management app.'"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sanity check

# COMMAND ----------

summary = spark.sql(
    f"""
    SELECT risk_band,
           count(*)                         AS reservations,
           round(avg(cancel_probability),4) AS avg_prob,
           round(min(cancel_probability),4) AS min_prob,
           round(max(cancel_probability),4) AS max_prob
    FROM {TARGET}
    GROUP BY risk_band
    ORDER BY avg_prob DESC
    """
)
summary.show()

total = spark.table(TARGET).count()
print(f"reservation_risk rows: {total:,} (model v{model_version})")

dbutils.notebook.exit(
    __import__("json").dumps({"target": TARGET, "rows": total, "model_version": model_version})
)
