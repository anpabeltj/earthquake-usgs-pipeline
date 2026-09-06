"""
Fetch significant earthquake records from the NCEI hazard service.

Where USGS records every event above the magnitude threshold, NCEI
holds only the ones that did damage: a death, roughly a million dollars
of damage, magnitude 7.5 and up, MMI X and up, or a tsunami. About
1,472 events fall in the 2000 to present window, against 186 thousand
in the USGS catalog. That narrowness is the point of the source: USGS
answers where earthquakes happen, NCEI answers what they cost.

The API paginates at 200 records per page and reports totalPages in the
response, so the loop below follows that rather than guessing.

Field names arrive in camelCase and are mapped to the snake_case column
names used everywhere else in this project. Everything else is left as
sent: the split date parts are assembled into a timestamp in silver,
not here, so a malformed date fails in a model rather than rejecting
the whole load job.

Cite as: National Geophysical Data Center / World Data Service
(NGDC/WDS): NCEI/WDS Global Significant Earthquake Database. NOAA
National Centers for Environmental Information. doi:10.7289/V5TD9V7K
"""

import logging
import os
import time

import requests

QUERY_URL = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/earthquakes"

# Matches the USGS backfill window, so both sources cover the same
# period and events can be compared like for like.
START_YEAR = int(os.getenv("NCEI_START_YEAR", "2000"))
END_YEAR = int(os.getenv("NCEI_END_YEAR", "2026"))

# The API caps a page at 200 and rejects more.
ITEMS_PER_PAGE = 200

REQUEST_TIMEOUT_SECONDS = 120

# No rate limit is documented for this service, and the whole 26 year
# window is only eight pages, so a second between calls costs nothing
# and keeps the pipeline a considerate client.
PAUSE_BETWEEN_REQUESTS_SECONDS = 1

# NOAA asks automated clients to identify themselves so they can reach
# the operator of a misbehaving one.
USER_AGENT = os.getenv(
    "NCEI_USER_AGENT",
    "usgs-earthquake-pipeline (student project; contact via github.com/anpabeltj)",
)

# A guard against an unexpected response shape looping forever.
MAX_PAGES = 50

logger = logging.getLogger(__name__)


def fetch_page(page):
    """Fetch one page and return its records and the page count."""
    params = {
        "minYear": START_YEAR,
        "maxYear": END_YEAR,
        "page": page,
        "itemsPerPage": ITEMS_PER_PAGE,
    }

    response = requests.get(
        QUERY_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict) or "items" not in payload:
        raise RuntimeError(f"unexpected NCEI response: {payload}")

    return payload.get("items", []), int(payload.get("totalPages", 1))


def build_row(record, ingested_at):
    """
    Flatten one NCEI record into a bronze row.

    Most fields are absent rather than null when NCEI has no figure, so
    every lookup goes through .get and lands as null in BigQuery.
    """
    return {
        "ncei_id": record.get("id"),
        "year": record.get("year"),
        "month": record.get("month"),
        "day": record.get("day"),
        "hour": record.get("hour"),
        "minute": record.get("minute"),
        "second": record.get("second"),

        "location_name": record.get("locationName"),
        "country": record.get("country"),
        "area": record.get("area"),
        "region_code": record.get("regionCode"),
        "latitude": record.get("latitude"),
        "longitude": record.get("longitude"),

        "eq_depth": record.get("eqDepth"),
        "eq_magnitude": record.get("eqMagnitude"),
        "eq_mag_mw": record.get("eqMagMw"),
        "eq_mag_ms": record.get("eqMagMs"),
        "eq_mag_mb": record.get("eqMagMb"),
        "eq_mag_ml": record.get("eqMagMl"),
        "eq_mag_unk": record.get("eqMagUnk"),
        "intensity": record.get("intensity"),

        "deaths": record.get("deaths"),
        "injuries": record.get("injuries"),
        "damage_millions_dollars": record.get("damageMillionsDollars"),
        "houses_destroyed": record.get("housesDestroyed"),
        "houses_damaged": record.get("housesDamaged"),

        "deaths_total": record.get("deathsTotal"),
        "injuries_total": record.get("injuriesTotal"),
        "damage_millions_dollars_total": record.get("damageMillionsDollarsTotal"),
        "houses_destroyed_total": record.get("housesDestroyedTotal"),
        "houses_damaged_total": record.get("housesDamagedTotal"),

        "deaths_amount_order": record.get("deathsAmountOrder"),
        "injuries_amount_order": record.get("injuriesAmountOrder"),
        "damage_amount_order": record.get("damageAmountOrder"),
        "houses_destroyed_amount_order": record.get("housesDestroyedAmountOrder"),
        "houses_damaged_amount_order": record.get("housesDamagedAmountOrder"),

        "tsunami_event_id": record.get("tsunamiEventId"),
        "volcano_event_id": record.get("volcanoEventId"),

        "_ingested_at": ingested_at,
    }


def fetch_ncei_rows(ingested_at):
    """Fetch every page and return rows ready for bronze."""
    rows = []
    page = 1
    total_pages = 1

    while page <= total_pages and page <= MAX_PAGES:
        records, total_pages = fetch_page(page)

        logger.info("ncei page %s of %s, %s records", page, total_pages, len(records))

        for record in records:
            rows.append(build_row(record, ingested_at))

        page = page + 1
        time.sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)

    logger.info("collected %s ncei rows", len(rows))

    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    sample = fetch_ncei_rows(now)

    print("rows:", len(sample))
    if sample:
        print("first row:", sample[0])