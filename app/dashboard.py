"""
Streamlit dashboard for the USGS earthquake pipeline.

Reads the gold layer directly. Every query filters on event_date so
BigQuery prunes partitions instead of scanning 26 years of data.

The layout follows the three analytical questions:
  1. When and where do earthquakes occur most often?
  2. Which regions and countries record the strongest events?
  3. How are magnitude and depth distributed?
"""

import os

import pandas as pd
import streamlit as st
from google.cloud import bigquery

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GOLD_DATASET = os.getenv("BQ_GOLD_DATASET", "gold")

CACHE_TTL_SECONDS = 300

st.set_page_config(
    page_title="Global Earthquake Monitor",
    layout="wide",
)


@st.cache_resource
def get_client():
    """One BigQuery client per session, reused across reruns."""
    return bigquery.Client(project=PROJECT_ID)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def run_query(sql, start_date, end_date):
    """
    Run a parameterised query against the gold layer.

    Dates go in as parameters rather than being formatted into the
    string, so BigQuery can cache the plan and odd input cannot break
    the query.
    """
    client = get_client()

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
        ]
    )

    return client.query(sql, job_config=job_config).to_dataframe()


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_date_bounds():
    """Earliest and latest day on record, used to bound the date picker."""
    client = get_client()

    sql = f"""
        select
            min(event_date) as first_date,
            max(event_date) as last_date
        from `{PROJECT_ID}.{GOLD_DATASET}.gold_fact_earthquake`
    """

    result = client.query(sql).to_dataframe()

    if result.empty or pd.isna(result.loc[0, "first_date"]):
        return None, None

    return result.loc[0, "first_date"], result.loc[0, "last_date"]


def table(name):
    return f"`{PROJECT_ID}.{GOLD_DATASET}.{name}`"


# ----------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------

st.sidebar.header("Filters")

first_date, last_date = get_date_bounds()

if first_date is None:
    st.warning("No earthquakes recorded yet. Run the backfill DAG first.")
    st.stop()

# Defaults to the last full year rather than the whole catalog, since
# 26 years at once makes the daily chart unreadable.
default_start = max(first_date, last_date.replace(year=last_date.year - 1))

start_date = st.sidebar.date_input(
    "From", value=default_start, min_value=first_date, max_value=last_date
)
end_date = st.sidebar.date_input(
    "To", value=last_date, min_value=first_date, max_value=last_date
)

if start_date > end_date:
    st.sidebar.error("Start date is after end date.")
    st.stop()

st.sidebar.caption(
    f"Catalog covers {first_date:%d %b %Y} to {last_date:%d %b %Y}. "
    "Only magnitude 4.5 and above, and only tectonic earthquakes."
)


# ----------------------------------------------------------------
# Headline numbers
# ----------------------------------------------------------------

st.title("Global Earthquake Monitor")
st.caption("USGS earthquake catalog, magnitude 4.5 and above")

summary_sql = f"""
    select
        count(*) as total_events,
        round(avg(magnitude), 2) as avg_magnitude,
        max(magnitude) as max_magnitude,
        countif(tsunami_flag = 1) as tsunami_flagged
    from {table('gold_fact_earthquake')}
    where event_date between @start_date and @end_date
"""

summary = run_query(summary_sql, start_date, end_date)

if summary.empty or summary.loc[0, "total_events"] == 0:
    st.warning("No earthquakes in this period.")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Earthquakes", f"{int(summary.loc[0, 'total_events']):,}")
col2.metric("Average magnitude", summary.loc[0, "avg_magnitude"])
col3.metric("Strongest", summary.loc[0, "max_magnitude"])
col4.metric("Tsunami flagged", f"{int(summary.loc[0, 'tsunami_flagged']):,}")

st.divider()


# ----------------------------------------------------------------
# Question 1: when and where
# ----------------------------------------------------------------

st.header("When and where do earthquakes occur most often?")

left, right = st.columns(2)

with left:
    st.subheader("Events per month")

    monthly_sql = f"""
        select
            date_trunc(event_date, month) as month,
            count(*) as events
        from {table('gold_fact_earthquake')}
        where event_date between @start_date and @end_date
        group by month
        order by month
    """

    monthly = run_query(monthly_sql, start_date, end_date)
    monthly["month"] = pd.to_datetime(monthly["month"]).dt.strftime("%b %Y")

    st.line_chart(monthly, x="month", y="events", height=280)

with right:
    st.subheader("Events by hour of day")

    hourly_sql = f"""
        select
            time.hour as hour_of_day,
            count(*) as events
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_time')} as time
            using (time_id)
        where fact.event_date between @start_date and @end_date
        group by hour_of_day
        order by hour_of_day
    """

    hourly = run_query(hourly_sql, start_date, end_date)

    # Hours with no events are missing from the result, so the axis
    # would otherwise skip them.
    all_hours = pd.DataFrame({"hour_of_day": range(24)})
    hourly = all_hours.merge(hourly, on="hour_of_day", how="left").fillna({"events": 0})
    hourly["events"] = hourly["events"].astype(int)

    st.bar_chart(hourly, x="hour_of_day", y="events", height=280)
    st.caption(
        "Hour in UTC. A flat distribution here is the expected result, "
        "since tectonic activity does not follow the clock."
    )

st.subheader("Events by continent")

# Ocean events have no continent, so the region name stands in for one.
# Inventing a label would hide the fact that these sit in international
# waters rather than in any country.
continent_sql = f"""
    select
        coalesce(location.continent, location.region, 'Unknown') as continent,
        count(*) as events
    from {table('gold_fact_earthquake')} as fact
    inner join {table('gold_dim_location')} as location
        using (location_id)
    where fact.event_date between @start_date and @end_date
    group by continent
    order by events
"""

continents = run_query(continent_sql, start_date, end_date)
st.bar_chart(continents, x="continent", y="events", horizontal=True, height=320)

st.subheader("Recent epicentres")

map_sql = f"""
    select latitude, longitude
    from {table('gold_fact_earthquake')}
    where event_date between @start_date and @end_date
      and event_date >= date_sub(@end_date, interval 30 day)
"""

recent = run_query(map_sql, start_date, end_date)
st.map(recent, latitude="latitude", longitude="longitude", size=30000)
st.caption("Last 30 days of the selected range, to keep the map readable.")

st.divider()


# ----------------------------------------------------------------
# Question 2: which regions record the strongest events
# ----------------------------------------------------------------

st.header("Which countries record the strongest earthquakes?")

country_sql = f"""
    select
        coalesce(location.country, location.region, 'Unknown') as country,
        count(*) as events,
        round(avg(fact.magnitude), 2) as avg_magnitude,
        max(fact.magnitude) as max_magnitude
    from {table('gold_fact_earthquake')} as fact
    inner join {table('gold_dim_location')} as location
        using (location_id)
    where fact.event_date between @start_date and @end_date
    group by country
    having events >= 10
    order by max_magnitude desc, events desc
    limit 20
"""

countries = run_query(country_sql, start_date, end_date)

chart_col, table_col = st.columns([2, 1])

with chart_col:
    st.bar_chart(
        countries.sort_values("events"),
        x="country",
        y="events",
        horizontal=True,
        height=520,
    )

with table_col:
    st.dataframe(countries, hide_index=True, height=520)

st.caption(
    "Countries with fewer than ten events are hidden. Entries such as "
    "Southwest Indian Ridge are seismic regions in international waters, "
    "which belong to no country and are shown under their own name."
)

st.divider()


# ----------------------------------------------------------------
# Question 3: magnitude and depth distribution
# ----------------------------------------------------------------

st.header("How are magnitude and depth distributed?")

left, right = st.columns(2)

with left:
    st.subheader("By magnitude band")

    magnitude_sql = f"""
        select
            magnitude_cat.magnitude_category,
            count(*) as events
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_magnitude_category')} as magnitude_cat
            using (magnitude_category_id)
        where fact.event_date between @start_date and @end_date
        group by magnitude_category
    """

    magnitudes = run_query(magnitude_sql, start_date, end_date)

    band_order = ["Minor", "Light", "Moderate", "Strong", "Major"]
    magnitudes["magnitude_category"] = pd.Categorical(
        magnitudes["magnitude_category"], categories=band_order, ordered=True
    )
    magnitudes = magnitudes.sort_values("magnitude_category")

    st.bar_chart(magnitudes, x="magnitude_category", y="events", height=300)

with right:
    st.subheader("By depth band")

    depth_sql = f"""
        select
            depth_cat.depth_category,
            count(*) as events
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_depth_category')} as depth_cat
            using (depth_category_id)
        where fact.event_date between @start_date and @end_date
        group by depth_category
    """

    depths = run_query(depth_sql, start_date, end_date)

    depth_order = ["Shallow", "Intermediate", "Deep"]
    depths["depth_category"] = pd.Categorical(
        depths["depth_category"], categories=depth_order, ordered=True
    )
    depths = depths.sort_values("depth_category")

    st.bar_chart(depths, x="depth_category", y="events", height=300)

st.caption(
    "Bands follow the conventional seismological thresholds rather than "
    "anything derived from this dataset."
)

st.divider()
st.caption(f"Source: USGS Earthquake Catalog. Showing {start_date} to {end_date}.")
