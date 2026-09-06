"""
Load NCEI significant earthquake records into the bronze layer.

Uses the same load job approach as the other loaders, and reuses the
NDJSON helper from load_to_bronze. Kept in its own module because it is
a separate source with its own table and its own schedule: NCEI revises
death tolls and damage figures as reports come in, but nothing like
hourly.

The whole series is refetched on every run. At 1,472 rows that costs
almost nothing, and it is the only way to pick up revisions, since the
API gives no way to ask what changed.
"""

import logging
import os
from datetime import datetime, timezone
from io import BytesIO

from google.cloud import bigquery

from extract_ncei import fetch_ncei_rows
from load_to_bronze import rows_to_ndjson

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BRONZE_DATASET = os.getenv("BQ_BRONZE_DATASET", "bronze")
BQ_LOCATION = os.getenv("BQ_LOCATION", "asia-southeast2")

NCEI_TABLE = "bronze_ncei_earthquake"

logger = logging.getLogger(__name__)


def get_ncei_table_id():
    return f"{PROJECT_ID}.{BRONZE_DATASET}.{NCEI_TABLE}"


def load_ncei_to_bronze():
    """Fetch every NCEI record in the window and append it to bronze."""
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT_ID is not set")

    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = fetch_ncei_rows(ingested_at)

    if not rows:
        logger.warning("ncei returned no rows")
        return 0

    client = bigquery.Client(project=PROJECT_ID)
    table_id = get_ncei_table_id()

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )

    payload = rows_to_ndjson(rows).encode("utf-8")

    job = client.load_table_from_file(
        BytesIO(payload),
        table_id,
        job_config=job_config,
        location=BQ_LOCATION,
    )

    job.result()

    logger.info("loaded %s rows into %s", job.output_rows, table_id)
    return job.output_rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load_ncei_to_bronze()