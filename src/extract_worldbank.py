"""
Fetch total population by country from the World Bank Indicators API.

Used to turn raw earthquake counts into something about people: a
country with two hundred million residents and forty earthquakes a year
is not in the same position as an uninhabited ridge with the same count.

The API answers with a two element array, metadata first and records
second, and paginates. Both are handled here.

No authentication and no rate limit are documented. Aggregates such as
"World" and "Africa Eastern and Southern" come back alongside real
countries; they are left in bronze as sent and filtered out later by
joining on ISO3 against the region seed, which only holds real
countries.
"""

import logging
import os
import time

import requests

INDICATOR = "SP.POP.TOTL"
QUERY_URL = f"https://api.worldbank.org/v2/country/all/indicator/{INDICATOR}"

# Earthquake history starts in 2000, so earlier population years would
# never be joined to anything. The upper bound is deliberately past the
# present: the API simply returns nothing for years it has not published.
START_YEAR = int(os.getenv("POPULATION_START_YEAR", "2000"))
END_YEAR = int(os.getenv("POPULATION_END_YEAR", "2030"))

PER_PAGE = 1000
REQUEST_TIMEOUT_SECONDS = 120
PAUSE_BETWEEN_REQUESTS_SECONDS = 1

# A guard against an unexpected response shape looping forever.
MAX_PAGES = 50

logger = logging.getLogger(__name__)


def fetch_page(page):
    """Fetch one page and return its metadata and records."""
    params = {
        "format": "json",
        "date": f"{START_YEAR}:{END_YEAR}",
        "per_page": PER_PAGE,
        "page": page,
    }

    response = requests.get(QUERY_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()

    payload = response.json()

    # A successful call answers with [metadata, records]. An error
    # answers with a single object instead, so the shape is worth
    # checking rather than assuming.
    if not isinstance(payload, list) or len(payload) < 2:
        raise RuntimeError(f"unexpected World Bank response: {payload}")

    metadata = payload[0] or {}
    records = payload[1] or []

    return metadata, records


def build_row(record, ingested_at):
    """Flatten one World Bank record into a bronze row."""
    country = record.get("country") or {}
    date_value = record.get("date")

    return {
        "iso3": record.get("countryiso3code"),
        "country_name": country.get("value"),
        "year": int(date_value) if date_value else None,
        "population": record.get("value"),
        "_ingested_at": ingested_at,
    }


def fetch_population_rows(ingested_at):
    """Fetch every page and return rows ready for bronze."""
    rows = []
    page = 1
    total_pages = 1

    while page <= total_pages and page <= MAX_PAGES:
        metadata, records = fetch_page(page)

        total_pages = int(metadata.get("pages", 1))
        logger.info("world bank page %s of %s, %s records", page, total_pages, len(records))

        for record in records:
            rows.append(build_row(record, ingested_at))

        page = page + 1
        time.sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)

    logger.info("collected %s population rows", len(rows))

    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    sample = fetch_population_rows(now)

    print("rows:", len(sample))
    if sample:
        print("first row:", sample[0])