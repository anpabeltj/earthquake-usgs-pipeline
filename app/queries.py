"""
Every BigQuery call the dashboard makes.

Kept apart from the rendering code so the SQL can be read, and the
caching reasoned about, without wading through layout. Each function
returns a DataFrame and knows nothing about how it will be drawn.
"""

import pandas as pd
import streamlit as st
from google.cloud import bigquery



from config import (
    CACHE_TTL_SECONDS,
    COUNTRY_CLAUSE,
    GOLD_DATASET,
    MAP_POINT_LIMIT,
    PROJECT_ID,
    MIN_DEATHS_FOR_RANKING,
    SIGNIFICANT_MAGNITUDE,
    table,
)


@st.cache_resource
def get_client():
    """One BigQuery client per session, reused across reruns."""
    return bigquery.Client(project=PROJECT_ID)


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def run_query(sql, start_date, end_date, countries=()):
    """
    Run a parameterised query against the gold layer.

    Dates and the country filter go in as parameters rather than being
    formatted into the string, so BigQuery can cache the plan and odd
    input cannot break the query. countries is a tuple rather than a
    list so Streamlit can hash it for the cache key.
    """
    client = get_client()

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
            bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            bigquery.ArrayQueryParameter("countries", "STRING", list(countries)),
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


@st.cache_data(ttl=CACHE_TTL_SECONDS)
def get_country_list():
    """Every country that has at least one event attributed to it."""
    client = get_client()

    sql = f"""
        select distinct country
        from `{PROJECT_ID}.{GOLD_DATASET}.gold_dim_location`
        where country is not null
        order by country
    """

    return client.query(sql).to_dataframe()["country"].tolist()


def get_summary(start_date, end_date, countries):
    """Headline counts for the selected range."""
    sql = f"""
        select
            count(*) as total_events,
            round(avg(fact.magnitude), 2) as avg_magnitude,
            max(fact.magnitude) as max_magnitude,
            countif(fact.magnitude >= {SIGNIFICANT_MAGNITUDE}) as significant_events
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_location')} as location
            using (location_id)
        where fact.event_date between @start_date and @end_date
        {COUNTRY_CLAUSE}
    """
    return run_query(sql, start_date, end_date, countries)


def get_monthly_events(start_date, end_date, countries):
    """Event count per calendar month."""
    sql = f"""
        select
            date_trunc(fact.event_date, month) as month,
            count(*) as events
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_location')} as location
            using (location_id)
        where fact.event_date between @start_date and @end_date
        {COUNTRY_CLAUSE}
        group by month
        order by month
    """
    return run_query(sql, start_date, end_date, countries)


def get_hourly_events(start_date, end_date, countries):
    """Event count per hour of day, UTC."""
    sql = f"""
        select
            time.hour as hour_of_day,
            count(*) as events
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_time')} as time
            using (time_id)
        inner join {table('gold_dim_location')} as location
            using (location_id)
        where fact.event_date between @start_date and @end_date
        {COUNTRY_CLAUSE}
        group by hour_of_day
        order by hour_of_day
    """
    return run_query(sql, start_date, end_date, countries)


def get_continent_events(start_date, end_date):
    """
    Event count per continent, worldwide.

    Deliberately takes no country filter. Filtering this to one country
    collapses it to a single bar, which says nothing, so it stays global
    and acts as the backdrop the filtered charts are read against.

    Falls back to a single "Unmapped location" bucket rather than the
    raw region text. Region text varies per event (ocean ridge names,
    fracture zones, or place strings that never matched the seed), so
    falling back to it per row split what should be a handful of
    continents into dozens of one-off bars.
    """
    sql = f"""
        select
            coalesce(location.continent, 'Unmapped location') as continent,
            count(*) as events
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_location')} as location
            using (location_id)
        where fact.event_date between @start_date and @end_date
        group by continent
    """
    return run_query(sql, start_date, end_date)


def get_epicentres(start_date, end_date, countries):
    """Coordinates for the map, most recent first and capped."""
    sql = f"""
        select fact.latitude, fact.longitude
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_location')} as location
            using (location_id)
        where fact.event_date between @start_date and @end_date
        {COUNTRY_CLAUSE}
        order by fact.event_date desc
        limit {MAP_POINT_LIMIT}
    """
    return run_query(sql, start_date, end_date, countries)


def get_felt_impact(start_date, end_date, countries):
    """
    Countries ranked by how strongly their earthquakes were felt.

    Ranked by cdi, the community determined intensity from public Did
    You Feel It reports, not by raw magnitude. A high magnitude event
    far out at sea can be barely felt by anyone, while a smaller event
    near a populated area can be felt strongly. cdi is what actually
    captures that, magnitude does not. Events with no cdi carry no
    public reports, so they are excluded rather than counted as zero
    impact.
    """
    sql = f"""
        select
            coalesce(location.country, location.region, 'Unknown') as country,
            count(*) as felt_events,
            round(avg(fact.cdi), 2) as avg_felt_intensity,
            sum(fact.felt_reports) as total_felt_reports
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_location')} as location
            using (location_id)
        where fact.event_date between @start_date and @end_date
          and fact.cdi is not null
        {COUNTRY_CLAUSE}
        group by country
        having felt_events >= 5
        order by avg_felt_intensity desc
        limit 20
    """
    return run_query(sql, start_date, end_date, countries)


def get_significant_by_year(start_date, end_date, countries):
    """Significant event count and share per year."""
    sql = f"""
        select
            extract(year from fact.event_date) as year,
            countif(fact.magnitude >= {SIGNIFICANT_MAGNITUDE}) as significant_events,
            count(*) as total_events,
            round(
                countif(fact.magnitude >= {SIGNIFICANT_MAGNITUDE}) / count(*) * 100,
                2
            ) as pct_significant
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_location')} as location
            using (location_id)
        where fact.event_date between @start_date and @end_date
        {COUNTRY_CLAUSE}
        group by year
        order by year
    """
    return run_query(sql, start_date, end_date, countries)


def get_impact_by_country(start_date, end_date, countries):
    """
    Recorded deaths per country, with population alongside.

    Reads gold_country_impact, which covers NCEI events only. Those are
    the damaging earthquakes, a different and much smaller set than the
    USGS catalog every other section draws on.
    """
    sql = f"""
        select
            country,
            sum(events) as events,
            sum(events_with_deaths) as events_with_deaths,
            sum(deaths) as deaths,
            sum(injuries) as injuries,
            max(population) as population,
            round(sum(deaths) / max(population) * 1000000, 2) as deaths_per_million
        from {table('gold_country_impact')}
        where year between extract(year from @start_date) and extract(year from @end_date)
          and population is not null
          and deaths is not null
          and (array_length(@countries) = 0 or country in unnest(@countries))
        group by country
        having deaths >= {MIN_DEATHS_FOR_RANKING}
        order by deaths_per_million desc
        limit 20
    """
    return run_query(sql, start_date, end_date, countries)


def get_deadliest_events(start_date, end_date, countries):
    """The individual earthquakes behind the country totals."""
    sql = f"""
        select
            event_date,
            location_name,
            country,
            eq_magnitude,
            deaths,
            injuries,
            damage_millions_dollars,
            caused_tsunami
        from {table('gold_earthquake_impact')}
        where event_date between @start_date and @end_date
          and deaths is not null
          and (array_length(@countries) = 0 or country in unnest(@countries))
        order by deaths desc
        limit 10
    """
    return run_query(sql, start_date, end_date, countries)


def get_magnitude_bands(start_date, end_date, countries):
    """Event count per magnitude band."""
    sql = f"""
        select
            magnitude_cat.magnitude_category,
            count(*) as events
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_magnitude_category')} as magnitude_cat
            using (magnitude_category_id)
        inner join {table('gold_dim_location')} as location
            using (location_id)
        where fact.event_date between @start_date and @end_date
        {COUNTRY_CLAUSE}
        group by magnitude_category
    """
    return run_query(sql, start_date, end_date, countries)


def get_depth_bands(start_date, end_date, countries):
    """Event count per depth band."""
    sql = f"""
        select
            depth_cat.depth_category,
            count(*) as events
        from {table('gold_fact_earthquake')} as fact
        inner join {table('gold_dim_depth_category')} as depth_cat
            using (depth_category_id)
        inner join {table('gold_dim_location')} as location
            using (location_id)
        where fact.event_date between @start_date and @end_date
        {COUNTRY_CLAUSE}
        group by depth_category
    """
    return run_query(sql, start_date, end_date, countries)

def get_impact_events(start_date, end_date, countries):
    """
    Every NCEI event in range, for the exploration section.

    Returns the whole set rather than a pre-aggregated one, since the
    reader chooses the grouping. At around 1,500 rows for the full
    26 years this is small enough to aggregate in pandas.
    """
    sql = f"""
        select
            event_date,
            location_name,
            country,
            continent,
            decade,
            eq_magnitude,
            eq_depth,
            intensity,
            magnitude_category,
            depth_category,
            caused_tsunami,
            deaths,
            injuries,
            damage_millions_dollars,
            houses_destroyed
        from {table('gold_earthquake_impact')}
        where event_date between @start_date and @end_date
          and (array_length(@countries) = 0 or country in unnest(@countries))
    """
    return run_query(sql, start_date, end_date, countries)