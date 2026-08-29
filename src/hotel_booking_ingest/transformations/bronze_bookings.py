"""Bronze: land the raw Hotel Booking Demand CSV via Auto Loader.

Auto Loader incrementally ingests any file dropped into the source volume path, so
re-landing the same CSV does not double-count (the pipeline manages the checkpoint).
Bronze is append-only with file lineage and no business transforms.
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F

# Set on the pipeline resource (configuration.source_volume_path). Falls back to the
# conventional path so the file is runnable/inspectable outside a deployed pipeline.
try:
    SOURCE_PATH = spark.conf.get("source_volume_path")  # noqa: F821  (spark injected by SDP)
except Exception:
    SOURCE_PATH = "/Volumes/main/hotel_booking_dev/raw/hotel_bookings/"


@dp.table(
    name="bronze_bookings",
    comment="Raw hotel bookings landed from CSV via Auto Loader. Append-only with file lineage.",
    table_properties={
        "delta.autoOptimize.optimizeWrite": "true",
        "delta.autoOptimize.autoCompact": "true",
    },
)
def bronze_bookings():
    return (
        spark.readStream.format("cloudFiles")  # noqa: F821
        .option("cloudFiles.format", "csv")
        .option("header", "true")
        .option("cloudFiles.inferColumnTypes", "true")
        .option("rescuedDataColumn", "_rescued_data")
        .load(SOURCE_PATH)
        .withColumn("_ingested_at", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
    )
