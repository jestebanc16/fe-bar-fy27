# Databricks notebook source
# MAGIC %md
# MAGIC # Train the cancellation-probability classifier
# MAGIC
# MAGIC Classic-ML slice of the end-to-end project. Trains a supervised classifier that
# MAGIC predicts P(cancel) for a hotel booking, reading the governed `silver_bookings` table.
# MAGIC
# MAGIC - sklearn `Pipeline` (one-hot categoricals + `HistGradientBoostingClassifier`).
# MAGIC - **Temporal** train/test split on `arrival_date` (train earliest ~80%, test latest
# MAGIC   ~20%) - honest evaluation that matches scoring future arrivals.
# MAGIC - MLflow tracking: ROC-AUC, PR-AUC, precision/recall/F1, confusion matrix,
# MAGIC   permutation feature importance (plots logged + shown inline).
# MAGIC - Registers to Unity Catalog `{catalog}.{schema}.hotel_cancel_classifier` and sets
# MAGIC   the `@champion` alias.
# MAGIC
# MAGIC Target-leakage columns are dropped explicitly (see `LEAKAGE` below).

# COMMAND ----------

dbutils.widgets.text("catalog", "", "Unity Catalog catalog")
dbutils.widgets.text("schema", "", "Schema holding silver_bookings")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
assert CATALOG and SCHEMA, "catalog and schema parameters are required"

MODEL_NAME = f"{CATALOG}.{SCHEMA}.hotel_cancel_classifier"
print(f"Source: {CATALOG}.{SCHEMA}.silver_bookings")
print(f"Model : {MODEL_NAME}")

# COMMAND ----------

import matplotlib.pyplot as plt
import mlflow
import numpy as np
import pandas as pd
from mlflow.models.signature import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    average_precision_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

mlflow.set_registry_uri("databricks-uc")

# Feature groups (intersected with the live schema for robustness).
CATEGORICAL = [
    "hotel",
    "meal",
    "market_segment",
    "distribution_channel",
    "reserved_room_type",
    "deposit_type",
    "customer_type",
]
NUMERIC = [
    "lead_time",
    "arrival_year",
    "arrival_date_week_number",
    "stays_in_weekend_nights",
    "stays_in_week_nights",
    "adults",
    "children",
    "babies",
    "is_repeated_guest",
    "previous_cancellations",
    "previous_bookings_not_canceled",
    "booking_changes",
    "days_in_waiting_list",
    "adr",
    "required_car_parking_spaces",
    "total_of_special_requests",
    "stay_nights",
]
# Dropped: post-outcome fields (reservation_status/date), is_canceled-derived
# (est_lost_revenue), room assigned at check-in (assigned_room_type), the surrogate key,
# PII-masked high-cardinality ids (agent/company), high-cardinality country, and metadata.
LEAKAGE = ["reservation_status", "reservation_status_date", "est_lost_revenue"]
LABEL = "is_canceled"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load + assemble features

# COMMAND ----------

pdf = spark.table(f"{CATALOG}.{SCHEMA}.silver_bookings").toPandas()
print(f"Loaded {len(pdf):,} rows")

cats = [c for c in CATEGORICAL if c in pdf.columns]
nums = [c for c in NUMERIC if c in pdf.columns]
features = cats + nums
print(f"Categorical ({len(cats)}): {cats}")
print(f"Numeric ({len(nums)}): {nums}")

# Fill: categoricals -> 'missing' (OHE needs no NaN); numerics -> 0.
X = pdf[features].copy()
X[cats] = X[cats].fillna("missing").astype(str)
X[nums] = X[nums].apply(pd.to_numeric, errors="coerce").fillna(0)
y = pdf[LABEL].astype(int)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Temporal split on `arrival_date`

# COMMAND ----------

arrival = pd.to_datetime(pdf["arrival_date"])
cutoff = arrival.quantile(0.8)
train_mask = (arrival < cutoff).to_numpy()
test_mask = ~train_mask

X_train, X_test = X[train_mask], X[test_mask]
y_train, y_test = y[train_mask], y[test_mask]
print(f"Cutoff arrival_date: {cutoff.date()}")
print(f"Train: {len(X_train):,} rows ({y_train.mean():.1%} canceled)")
print(f"Test : {len(X_test):,} rows ({y_test.mean():.1%} canceled)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Train + evaluate (MLflow tracked)

# COMMAND ----------

preprocess = ColumnTransformer(
    transformers=[
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cats),
        ("num", "passthrough", nums),
    ]
)
pipe = Pipeline(
    steps=[
        ("prep", preprocess),
        (
            "clf",
            HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.06, max_depth=8, random_state=42
            ),
        ),
    ]
)

mlflow.sklearn.autolog(log_models=False, silent=True)

with mlflow.start_run(run_name="hotel_cancel_hgb") as run:
    mlflow.log_params(
        {
            "estimator": "HistGradientBoostingClassifier",
            "n_categorical": len(cats),
            "n_numeric": len(nums),
            "split": "temporal",
            "split_cutoff": str(cutoff.date()),
            "n_train": len(X_train),
            "n_test": len(X_test),
        }
    )

    pipe.fit(X_train, y_train)

    proba = pipe.predict_proba(X_test)[:, 1]
    pred = (proba >= 0.5).astype(int)

    auc = roc_auc_score(y_test, proba)
    pr_auc = average_precision_score(y_test, proba)
    prec = precision_score(y_test, pred)
    rec = recall_score(y_test, pred)
    f1 = f1_score(y_test, pred)
    mlflow.log_metrics(
        {
            "test_roc_auc": auc,
            "test_pr_auc": pr_auc,
            "test_precision": prec,
            "test_recall": rec,
            "test_f1": f1,
        }
    )

    print(f"ROC-AUC : {auc:.4f}")
    print(f"PR-AUC  : {pr_auc:.4f}")
    print(f"Precision: {prec:.4f}  Recall: {rec:.4f}  F1: {f1:.4f}")
    print("\n" + classification_report(y_test, pred, target_names=["kept", "canceled"]))

    # --- Confusion matrix ---
    cm = confusion_matrix(y_test, pred)
    fig_cm, ax_cm = plt.subplots(figsize=(4.5, 4))
    ConfusionMatrixDisplay(cm, display_labels=["kept", "canceled"]).plot(ax=ax_cm)
    ax_cm.set_title(f"Confusion matrix (AUC={auc:.3f})")
    mlflow.log_figure(fig_cm, "confusion_matrix.png")

    # --- ROC + PR curves ---
    fpr, tpr, _ = roc_curve(y_test, proba)
    pr_p, pr_r, _ = precision_recall_curve(y_test, proba)
    fig_c, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    ax1.plot(fpr, tpr, label=f"AUC={auc:.3f}")
    ax1.plot([0, 1], [0, 1], "k--", alpha=0.3)
    ax1.set(xlabel="FPR", ylabel="TPR", title="ROC")
    ax1.legend()
    ax2.plot(pr_r, pr_p, label=f"AP={pr_auc:.3f}")
    ax2.set(xlabel="Recall", ylabel="Precision", title="Precision-Recall")
    ax2.legend()
    mlflow.log_figure(fig_c, "roc_pr_curves.png")

    # --- Permutation importance (subsample for speed) ---
    n_imp = min(5000, len(X_test))
    Xi = X_test.iloc[:n_imp]
    yi = y_test.iloc[:n_imp]
    perm = permutation_importance(
        pipe, Xi, yi, scoring="roc_auc", n_repeats=5, random_state=42, n_jobs=-1
    )
    imp = (
        pd.DataFrame({"feature": features, "importance": perm.importances_mean})
        .sort_values("importance", ascending=False)
        .head(15)
    )
    fig_i, ax_i = plt.subplots(figsize=(7, 5))
    ax_i.barh(imp["feature"][::-1], imp["importance"][::-1])
    ax_i.set_title("Permutation importance (top 15, ROC-AUC drop)")
    fig_i.tight_layout()
    mlflow.log_figure(fig_i, "feature_importance.png")
    print("\nTop features:")
    print(imp.to_string(index=False))

    # --- Register model ---
    signature = infer_signature(X_test, proba)
    logged = mlflow.sklearn.log_model(
        pipe,
        artifact_path="model",
        signature=signature,
        input_example=X_test.head(5),
        registered_model_name=MODEL_NAME,
    )
    run_id = run.info.run_id

print(f"\nLogged model: {logged.model_uri}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Promote to `@champion`

# COMMAND ----------

from mlflow.tracking import MlflowClient

client = MlflowClient()
# The version just registered from this run.
versions = client.search_model_versions(f"name = '{MODEL_NAME}'")
this_version = max(
    (v for v in versions if v.run_id == run_id), key=lambda v: int(v.version)
)
client.set_registered_model_alias(MODEL_NAME, "champion", this_version.version)
print(f"{MODEL_NAME} v{this_version.version} -> @champion")

dbutils.notebook.exit(
    __import__("json").dumps(
        {
            "model": MODEL_NAME,
            "version": int(this_version.version),
            "run_id": run_id,
            "roc_auc": round(float(auc), 4),
            "pr_auc": round(float(pr_auc), 4),
            "precision": round(float(prec), 4),
            "recall": round(float(rec), 4),
            "f1": round(float(f1), 4),
        }
    )
)
