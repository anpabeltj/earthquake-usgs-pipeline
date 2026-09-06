"""
Load World Bank population data into the bronze layer in BigQuery.

Uses the same load job approach as the earthquake loader, and reuses
its NDJSON helper. Kept in its own module because it is a separate
source with its own table and its own schedule: population is published
once a year, not once an hour.
"""

import logging
import os
from datetime import datetime, timezone
from io import BytesIO

from google.cloud import bigquery

from extract_worldbank import fetch_population_rows
from load_to_bronze import rows_to_ndjson

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BRONZE_DATASET = os.getenv("BQ_BRONZE_DATASET", "bronze")
BQ_LOCATION = os.getenv("BQ_LOCATION", "asia-southeast2")

POPULATION_TABLE = "bronze_worldbank_population"

logger = logging.getLogger(__name__)


def get_population_table_id():
    return f"{PROJECT_ID}.{BRONZE_DATASET}.{POPULATION_TABLE}"


def load_population_to_bronze():
    """
    Fetch the full indicator and append it to bronze.

    There is no date window to pass in. The whole series is a few
    thousand rows, and the World Bank revises past years as estimates
    are updated, so fetching everything each time is both cheap and the
    only way to pick those revisions up.
    """
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT_ID is not set")

    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = fetch_population_rows(ingested_at)

    if not rows:
        logger.warning("world bank returned no population rows")
        return 0

    client = bigquery.Client(project=PROJECT_ID)
    table_id = get_population_table_id()

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
    load_population_to_bronze()