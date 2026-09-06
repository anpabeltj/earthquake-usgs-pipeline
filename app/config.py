"""Constants shared across the dashboard."""

import os

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GOLD_DATASET = os.getenv("BQ_GOLD_DATASET", "gold")

CACHE_TTL_SECONDS = 300

# Matches significant_events in gold_country_exposure and the default
# alert threshold in telegram_notifier, so "significant" means the same
# thing everywhere in the project.
SIGNIFICANT_MAGNITUDE = 6.0

# NCEI records only damaging earthquakes, so a country needs a handful
# of them before a per-million figure means anything. Below this, one
# event drives the whole number.
MIN_DEATHS_FOR_RANKING = 100

# st.map slows to a crawl well before the full catalog fits on it, so
# the map draws the most recent events up to this many and says so.
MAP_POINT_LIMIT = 5000

# Ingestion runs hourly, so anything older than this means the pipeline
# is behind rather than that the world went quiet.
STALE_DATA_DAYS = 2

SORT_HIGH = "Highest first"
SORT_LOW = "Lowest first"
SORT_NAME = "A to Z"
SORT_OPTIONS = [SORT_HIGH, SORT_LOW, SORT_NAME]

MAGNITUDE_BAND_ORDER = ["Minor", "Light", "Moderate", "Strong", "Major"]
DEPTH_BAND_ORDER = ["Shallow", "Intermediate", "Deep"]

# Reused in most queries. An empty selection means no filtering at all,
# which keeps sea events in, since they have no country to match.
COUNTRY_CLAUSE = """
    and (
        array_length(@countries) = 0
        or location.country in unnest(@countries)
    )
"""


def table(name):
    """Fully qualified, backticked table reference."""
    return f"`{PROJECT_ID}.{GOLD_DATASET}.{name}`"

# Columns offered in the exploration section, split by what each chart
# type can actually plot. Keys are what the reader sees, values are the
# column names in gold_earthquake_impact.
EXPLORE_NUMERIC = {
    "Magnitude": "eq_magnitude",
    "Depth (km)": "eq_depth",
    "Deaths": "deaths",
    "Injuries": "injuries",
    "Damage (million USD)": "damage_millions_dollars",
    "Houses destroyed": "houses_destroyed",
    "Intensity (MMI)": "intensity",
}

EXPLORE_CATEGORICAL = {
    "Magnitude band": "magnitude_category",
    "Depth band": "depth_category",
    "Continent": "continent",
    "Country": "country",
    "Decade": "decade",
    "Caused tsunami": "caused_tsunami",
}

EXPLORE_AGGREGATIONS = {
    "Total": "sum",
    "Average": "mean",
    "Maximum": "max",
    "Event count": "count",
}


# Fixed order for the bands, so the axes read in their natural sequence
# rather than alphabetically.
BAND_ORDERS = {
    "magnitude_category": ["Minor", "Light", "Moderate", "Strong", "Major"],
    "depth_category": ["Shallow", "Intermediate", "Deep"],
}