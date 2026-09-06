"""
Load USGS events into the bronze layer in BigQuery.

Uses load jobs rather than streaming inserts. The streaming API refuses
to write to partitions older than 3650 days, which rules it out for a
backfill reaching back to 2000. Load jobs have no such limit, handle
large payloads in one request, and are free, so they suit bulk work far
better anyway.

Bronze is append only. Re-running the same date range writes the same
events again, which is fine and sometimes wanted: USGS revises magnitude
and depth after review, so a later run can carry a corrected version of
an event already stored. Silver keeps whichever copy has the newest
updated timestamp.
"""

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from io import BytesIO



from google.cloud import bigquery

from extract_usgs import fetch_bronze_rows

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BRONZE_DATASET = os.getenv("BQ_BRONZE_DATASET", "bronze")
BQ_LOCATION = os.getenv("BQ_LOCATION", "asia-southeast2")

BRONZE_TABLE = "bronze_usgs_earthquake"

EXPECTED_BACKFILL_START = date(2000, 1, 1)

logger = logging.getLogger(__name__)


def get_table_id():
    return f"{PROJECT_ID}.{BRONZE_DATASET}.{BRONZE_TABLE}"


def rows_to_ndjson(rows):
    """
    Turn the rows into newline delimited JSON.

    That is the format the load job expects, one JSON object per line
    with no surrounding array.
    """
    lines = []
    for row in rows:
        lines.append(json.dumps(row))

    return "\n".join(lines)


def load_rows(client, rows):
    """
    Append rows to bronze through a load job.

    The table already exists with a fixed schema, so nothing is
    autodetected and a payload with an unexpected field fails loudly
    rather than silently widening the table.
    """
    table_id = get_table_id()

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

    # Blocks until the load finishes, and raises if BigQuery rejected it.
    job.result()

    logger.info("loaded %s rows into %s", job.output_rows, table_id)
    return job.output_rows


def load_range_to_bronze(start_date, end_date):
    """
    Fetch one date range and write it to bronze.

    Airflow passes its data interval in, so the same function serves both
    the historical backfill and the hourly operational run.
    """
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT_ID is not set")

    ingested_at = datetime.now(timezone.utc).isoformat()
    rows = fetch_bronze_rows(start_date, end_date, ingested_at)

    if not rows:
        logger.info("no events between %s and %s", start_date, end_date)
        return 0

    client = bigquery.Client(project=PROJECT_ID)
    count = load_rows(client, rows)

    logger.info("bronze load finished for %s to %s, %s rows", start_date, end_date, count)
    return count


def get_max_source_date(client):
    """Return the latest _source_date already in bronze, or None if empty."""
    sql = f"select max(_source_date) as max_date from `{get_table_id()}`"
    result = list(client.query(sql).result())
    return result[0].max_date if result and result[0].max_date else None


def backfill_has_reached_start():
    """
    True once bronze holds data back to the historical start date.

    usgs_backfill runs on its own monthly schedule and can still be
    working through 26 years of history when usgs_pipeline is enabled.
    Checking bronze directly, rather than trying to sense a specific
    backfill DagRun, works regardless of how the two DAGs' schedules
    relate, since they don't share a comparable execution date.
    """
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT_ID is not set")

    client = bigquery.Client(project=PROJECT_ID)
    sql = f"select min(_source_date) as earliest from `{get_table_id()}`"
    result = list(client.query(sql).result())
    earliest = result[0].earliest if result else None

    return earliest is not None and earliest <= EXPECTED_BACKFILL_START


def close_ingestion_gap(data_interval_end, **context):
    """
    Fill in any missing days between the last recorded bronze date and
    now, in case the pipeline DAG was paused, disabled, or simply not
    running yet for a stretch of time between backfill finishing and
    the hourly pipeline starting.

    Chunked by month to stay under the USGS 20000 result cap, same
    approach as the backfill DAG. Safe to run every hour: when there is
    no gap, which is the normal case, this is a single cheap query and
    nothing else happens.
    """
    if not PROJECT_ID:
        raise ValueError("GCP_PROJECT_ID is not set")

    client = bigquery.Client(project=PROJECT_ID)
    max_date = get_max_source_date(client)
    today = data_interval_end.date()

    if max_date is None:
        logger.info("bronze is empty, nothing to catch up, run backfill first")
        return 0

    gap_start = max_date + timedelta(days=1)

    if gap_start >= today:
        logger.info("no gap to close, bronze is current through %s", max_date)
        return 0

    logger.warning(
        "gap detected: bronze last has %s, today is %s, catching up %s to %s",
        max_date, today, gap_start, today,
    )

    total = 0
    chunk_start = gap_start
    while chunk_start < today:
        chunk_end = min(chunk_start + timedelta(days=30), today)
        total += load_range_to_bronze(
            chunk_start.strftime("%Y-%m-%d"),
            chunk_end.strftime("%Y-%m-%d"),
        )
        chunk_start = chunk_end

    logger.info("gap closed, %s rows caught up", total)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load_range_to_bronze("2026-08-01", "2026-08-02")