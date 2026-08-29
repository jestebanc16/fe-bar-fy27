"""Gold: hotel x arrival-month KPIs for the revenue-management story.

Full-table aggregate (materialized view) over silver. Honest limit: true occupancy /
RevPAR need room inventory the dataset lacks, so this supports cancel rate + estimated
lost revenue and a room-night proxy only.
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F


@dp.materialized_view(
    name="gold_hotel_month",
    comment="Bookings, cancellations, cancel rate, ADR and estimated lost revenue per hotel and arrival month.",
    cluster_by=["hotel", "arrival_month_start"],
)
def gold_hotel_month():
    return (
        spark.read.table("silver_bookings")  # noqa: F821
        .withColumn(
            "arrival_month_start",
            F.trunc(F.col("arrival_date"), "month"),
        )
        .groupBy(
            "hotel",
            "arrival_year",
            F.month("arrival_date").alias("arrival_month"),
            "arrival_month_start",
        )
        .agg(
            F.count("*").alias("bookings"),
            F.sum(F.col("is_canceled").cast("int")).alias("cancellations"),
            F.round(F.avg(F.col("is_canceled").cast("int")), 4).alias("cancel_rate"),
            F.round(F.avg("adr"), 2).alias("avg_adr"),
            F.sum("stay_nights").alias("room_nights"),
            F.sum(
                F.when(F.col("is_canceled"), F.col("stay_nights")).otherwise(0)
            ).alias("canceled_room_nights"),
            F.sum("est_lost_revenue").alias("est_lost_revenue"),
        )
    )
