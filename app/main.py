"""
Streamlit dashboard for the USGS earthquake pipeline.

Reads the gold layer directly. Every query filters on event_date so
BigQuery prunes partitions instead of scanning 26 years of data.

The layout follows the three analytical questions from the project brief:
  1. Where do earthquakes happen the most?
  2. Which regions feel the strongest earthquake impact?
  3. How has the number of significant earthquakes changed each year?

Earthquakes per million people and the magnitude/depth breakdown are
supplementary. Useful context, but not one of the three core questions.

This file holds the filters and the page order only. The SQL lives in
queries.py, the chart specs in charts.py, and each section in
sections.py.
"""
import os
import sys
from datetime import date

import streamlit as st

# Streamlit runs this file through exec() rather than as a script, so
# the folder it lives in is not added to sys.path automatically the way
# python main.py would. Without this, the sibling modules below are
# invisible.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import queries
import sections
from config import STALE_DATA_DAYS

st.set_page_config(
    page_title="Global Earthquake Monitor",
    page_icon="🌍",
    layout="wide",
)


def render_sidebar():
    """
    Draw the filters and return the reader's choices.

    Returns (start_date, end_date, countries), or None when the catalog
    is empty or the dates are the wrong way round, meaning there is
    nothing to draw.
    """
    st.sidebar.header("🎛️ Filters")

    first_date, last_date = queries.get_date_bounds()

    if first_date is None:
        st.warning("No earthquakes recorded yet. Run the backfill DAG first.")
        return None

    today = date.today()

    # The picker runs to today rather than to the last recorded event, so
    # a quiet stretch and a stalled pipeline do not look the same.
    # Picking a range past the last event is allowed and simply returns
    # nothing for those days.
    picker_max = max(last_date, today)

    # Defaults to the last full year rather than the whole catalog, since
    # 26 years at once makes the monthly chart unreadable. Guarded
    # against last_date being Feb 29, which has no equivalent date in a
    # non leap previous year.
    try:
        one_year_back = last_date.replace(year=last_date.year - 1)
    except ValueError:
        one_year_back = last_date.replace(month=2, day=28, year=last_date.year - 1)

    default_start = max(first_date, one_year_back)

    start_date = st.sidebar.date_input(
        "From", value=default_start, min_value=first_date, max_value=picker_max
    )
    end_date = st.sidebar.date_input(
        "To", value=picker_max, min_value=first_date, max_value=picker_max
    )

    if start_date > end_date:
        st.sidebar.error("Start date is after end date.")
        return None

    selected_countries = st.sidebar.multiselect(
        "Countries",
        options=queries.get_country_list(),
        default=[],
        placeholder="All countries",
        help=(
            "Type to search. Leave empty for the whole world. Events at sea "
            "carry no country in the USGS place text, so they drop out once "
            "a filter is applied, which understates island nations in "
            "particular."
        ),
    )

    st.sidebar.caption(
        f"Catalog covers {first_date:%d %b %Y} to {last_date:%d %b %Y}. "
        "Only magnitude 4.5 and above, and only tectonic earthquakes."
    )

    days_behind = (today - last_date).days
    if days_behind > STALE_DATA_DAYS:
        st.sidebar.warning(
            f"Latest event on record is {last_date:%d %b %Y}, {days_behind} days "
            "ago. Ingestion is most likely behind rather than the world being "
            "quiet. Check the usgs_pipeline DAG."
        )

    if selected_countries:
        st.sidebar.info(
            f"Filtered to {len(selected_countries)} "
            f"{'country' if len(selected_countries) == 1 else 'countries'}. "
            "Events at sea are excluded while a filter is active, since they "
            "have no country to match."
        )

    return start_date, end_date, tuple(selected_countries)


filters = render_sidebar()

if filters is None:
    st.stop()

start_date, end_date, countries = filters

st.title("🌍 Global Earthquake Monitor")
st.caption("USGS earthquake catalog, magnitude 4.5 and above")

total_events = sections.render_summary(start_date, end_date, countries)

if total_events is None:
    st.stop()

st.divider()
sections.render_where(start_date, end_date, countries, total_events)

st.divider()
sections.render_impact_felt(start_date, end_date, countries)

st.divider()
sections.render_trend(start_date, end_date, countries)

st.divider()
sections.render_impact(start_date, end_date, countries)

st.divider()
sections.render_explore(start_date, end_date, countries)

st.divider()
sections.render_distribution(start_date, end_date, countries)

st.divider()
st.caption(f"📡 Source: USGS Earthquake Catalog. Showing {start_date} to {end_date}.")