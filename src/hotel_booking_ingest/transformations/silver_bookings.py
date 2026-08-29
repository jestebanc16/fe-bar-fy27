"""Silver: typed, cleaned bookings — one row per reservation.

Casts raw string/inferred columns to proper types, derives the arrival date, stay
length, and estimated lost revenue, and applies light data-quality expectations. This
grain is what the ML stage will read later, so no separate reservation-level gold.
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F

# arrival_date_month arrives as an English month name (e.g. "July").
_MONTH_NUM = F.from_unixtime(
    F.unix_timestamp(F.col("arrival_date_month"), "MMMM"), "MM"
).cast("int")


@dp.table(
    name="silver_bookings",
    comment="Typed and cleaned hotel bookings, one row per reservation.",
    cluster_by=["hotel", "arrival_date"],
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "delta.autoOptimize.autoCompact": "true",
        # arrival_date is derived (past the default first-32-column stats window);
        # name the skipping-stats columns explicitly so clustering has stats.
        "delta.dataSkippingStatsColumns": "hotel,arrival_date,arrival_year,adr",
    },
)
@dp.expect_or_drop("valid_hotel", "hotel IS NOT NULL")
@dp.expect_or_drop("non_negative_adr", "adr >= 0")
@dp.expect("has_guests", "(adults + children + babies) > 0")
@dp.expect("clean_parse", "_rescued_data IS NULL")
def silver_bookings():
    return (
        spark.readStream.table("bronze_bookings")  # noqa: F821
        .withColumn("is_canceled", F.col("is_canceled").cast("boolean"))
        .withColumn("lead_time", F.col("lead_time").cast("int"))
        .withColumn("arrival_year", F.col("arrival_date_year").cast("int"))
        .withColumn("arrival_month_num", _MONTH_NUM)
        .withColumn("arrival_day", F.col("arrival_date_day_of_month").cast("int"))
        .withColumn("adults", F.coalesce(F.col("adults").cast("int"), F.lit(0)))
        .withColumn("children", F.coalesce(F.col("children").cast("int"), F.lit(0)))
        .withColumn("babies", F.coalesce(F.col("babies").cast("int"), F.lit(0)))
        .withColumn(
            "stays_in_weekend_nights",
            F.coalesce(F.col("stays_in_weekend_nights").cast("int"), F.lit(0)),
        )
        .withColumn(
            "stays_in_week_nights",
            F.coalesce(F.col("stays_in_week_nights").cast("int"), F.lit(0)),
        )
        .withColumn("adr", F.col("adr").cast("decimal(10,2)"))
        .withColumn(
            "arrival_date",
            F.make_date("arrival_year", "arrival_month_num", "arrival_day"),
        )
        .withColumn(
            "stay_nights",
            F.col("stays_in_weekend_nights") + F.col("stays_in_week_nights"),
        )
        .withColumn(
            "est_lost_revenue",
            F.when(
                F.col("is_canceled"),
                (F.col("adr") * F.col("stay_nights")).cast("decimal(12,2)"),
            ).otherwise(F.lit(0).cast("decimal(12,2)")),
        )
        .drop("arrival_month_num")
    )
