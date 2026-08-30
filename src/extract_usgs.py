"""
Fetch earthquake data from the USGS earthquake catalog.

The service takes a start and end time, so one call covers a whole date
range. That is what makes the historical backfill possible: BMKG style
polling could only ever see the present, while this can reach back to
2000.

No filtering by event type happens here. The catalog also contains
quarry blasts, explosions, and ice quakes, and keeping them in bronze
lets us show how many were removed later instead of silently dropping
them at the source.
"""

import logging
import os
import time

import requests

QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

MIN_MAGNITUDE = float(os.getenv("USGS_MIN_MAGNITUDE", "4.5"))

REQUEST_TIMEOUT_SECONDS = 120

# The service rejects anything above 20000 results with a 400.
MAX_RESULTS_PER_REQUEST = 20000

# USGS publishes no rate limit, but the docs ask automated clients to be
# considerate. A short pause after each call costs a few minutes across
# the whole backfill and removes any doubt.
PAUSE_BETWEEN_REQUESTS_SECONDS = 1

logger = logging.getLogger(__name__)


def fetch_events(start_date, end_date):
    """
    Call the USGS catalog for one date range.

    start_date and end_date are strings in YYYY-MM-DD form. The range is
    inclusive of the start and exclusive of the end, which is how Airflow
    hands over its data interval.
    """
    params = {
        "format": "geojson",
        "starttime": start_date,
        "endtime": end_date,
        "minmagnitude": MIN_MAGNITUDE,
        "limit": MAX_RESULTS_PER_REQUEST,
        "orderby": "time-asc",
    }

    logger.info("requesting USGS events from %s to %s", start_date, end_date)

    response = requests.get(QUERY_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    payload = response.json()
    features = payload.get("features", [])

    logger.info("received %s events", len(features))

    time.sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)

    return features


def build_row(feature, ingested_at, source_date):
    """
    Flatten one GeoJSON feature into a bronze row.

    Types are left as USGS sent them. Unlike BMKG, this API already
    returns numbers as numbers, so casting them to text here would be
    adding a transformation rather than avoiding one.
    """
    properties = feature.get("properties", {})
    geometry = feature.get("geometry", {})
    coordinates = geometry.get("coordinates", [None, None, None])

    return {
        "usgs_id": feature.get("id"),
        "magnitude": properties.get("mag"),
        "place": properties.get("place"),
        "event_time_ms": properties.get("time"),
        "updated_ms": properties.get("updated"),
        "felt_reports": properties.get("felt"),
        "cdi": properties.get("cdi"),
        "mmi": properties.get("mmi"),
        "alert": properties.get("alert"),
        "status": properties.get("status"),
        "tsunami_flag": properties.get("tsunami"),
        "significance": properties.get("sig"),
        "network": properties.get("net"),
        "station_count": properties.get("nst"),
        "azimuthal_gap": properties.get("gap"),
        "rms": properties.get("rms"),
        "magnitude_type": properties.get("magType"),
        "event_type": properties.get("type"),
        "contributing_ids": properties.get("ids"),
        "contributing_sources": properties.get("sources"),
        "product_types": properties.get("types"),
        "longitude": coordinates[0],
        "latitude": coordinates[1],
        "depth_km": coordinates[2],
        "_ingested_at": ingested_at,
        "_source_date": source_date,
    }


def fetch_bronze_rows(start_date, end_date, ingested_at):
    """Fetch one date range and return rows ready for bronze."""
    features = fetch_events(start_date, end_date)

    rows = []
    for feature in features:
        rows.append(build_row(feature, ingested_at, start_date))

    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    sample = fetch_bronze_rows("2026-08-01", "2026-08-02", now)

    print("rows:", len(sample))
    if sample:
        print("first row:", sample[0])