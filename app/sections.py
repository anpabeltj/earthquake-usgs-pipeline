"""
One function per section of the dashboard.

Each takes the current filters and renders itself. Nothing here builds
SQL or chart specs directly, that belongs in queries.py and charts.py.
"""




import pandas as pd
import streamlit as st

import queries
from charts import (
    explore_heatmap,
    horizontal_bar,
    monthly_line,
    sort_ranking,
    vertical_bar,
)
from config import (
    BAND_ORDERS,
    DEPTH_BAND_ORDER,
    EXPLORE_AGGREGATIONS,
    EXPLORE_CATEGORICAL,
    EXPLORE_NUMERIC,
    MAGNITUDE_BAND_ORDER,
    MAP_POINT_LIMIT,
    MIN_DEATHS_FOR_RANKING,
    SIGNIFICANT_MAGNITUDE,
    SORT_OPTIONS,
)

def render_summary(start_date, end_date, countries):
    """Headline metrics. Returns the total, or None when nothing matches."""
    summary = queries.get_summary(start_date, end_date, countries)

    if summary.empty or summary.loc[0, "total_events"] == 0:
        st.warning("No earthquakes match these filters.")
        return None

    total_events = int(summary.loc[0, "total_events"])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🌐 Earthquakes", f"{total_events:,}")
    col2.metric("📐 Average magnitude", summary.loc[0, "avg_magnitude"])
    col3.metric("💥 Strongest", summary.loc[0, "max_magnitude"])
    col4.metric(
        f"⚡ M{SIGNIFICANT_MAGNITUDE}+ events",
        f"{int(summary.loc[0, 'significant_events']):,}",
    )

    return total_events


def render_where(start_date, end_date, countries, total_events):
    """Question 1: where do earthquakes happen the most."""
    st.header("📍 Where do earthquakes happen the most?")

    left, right = st.columns(2)

    with left:
        st.subheader("📈 Events per month")

        monthly = queries.get_monthly_events(start_date, end_date, countries)
        monthly["month"] = pd.to_datetime(monthly["month"])

        st.altair_chart(monthly_line(monthly), use_container_width=True)

    with right:
        st.subheader("🕐 Events by hour of day")

        hourly = queries.get_hourly_events(start_date, end_date, countries)

        # Hours with no events are missing from the result, so the axis
        # would otherwise skip them.
        all_hours = pd.DataFrame({"hour_of_day": range(24)})
        hourly = all_hours.merge(hourly, on="hour_of_day", how="left").fillna(
            {"events": 0}
        )
        hourly["events"] = hourly["events"].astype(int)

        st.bar_chart(hourly, x="hour_of_day", y="events", height=280)
        st.caption(
            "Hour in UTC. A flat distribution here is the expected result, "
            "since tectonic activity does not follow the clock."
        )

    st.subheader("🌎 Events by continent")

    continents = queries.get_continent_events(start_date, end_date)

    continent_sort = st.radio(
        "Sort continents by",
        SORT_OPTIONS,
        horizontal=True,
        key="continent_sort",
    )
    continents = sort_ranking(continents, "events", "continent", continent_sort)

    st.altair_chart(
        horizontal_bar(continents, "continent", "events", height=320),
        use_container_width=True,
    )
    st.caption(
        "Always worldwide, following the date range only, since filtering to "
        "one country would leave a single bar. Unmapped location covers "
        "events at sea or with a place description that matched no known "
        "country."
    )

    st.subheader("🗺️ Epicentres")

    epicentres = queries.get_epicentres(start_date, end_date, countries)

    if epicentres.empty:
        st.info("No events to map for these filters.")
        return

    st.map(epicentres, latitude="latitude", longitude="longitude", size=30000)

    if total_events > MAP_POINT_LIMIT:
        st.caption(
            f"Showing the {MAP_POINT_LIMIT:,} most recent of {total_events:,} "
            "events in range. Narrow the dates to map a period in full."
        )
    else:
        st.caption(f"All {total_events:,} events in the selected range.")


def render_impact_felt(start_date, end_date, countries):
    """Question 2: which regions feel the strongest impact."""
    st.header("💥 Which regions feel the strongest earthquake impact?")

    felt_impact = queries.get_felt_impact(start_date, end_date, countries)

    if felt_impact.empty:
        st.info("No events with public felt reports match these filters.")
        return

    felt_sort = st.radio(
        "Sort by",
        SORT_OPTIONS,
        horizontal=True,
        key="felt_sort",
    )
    felt_impact = sort_ranking(felt_impact, "avg_felt_intensity", "country", felt_sort)

    chart_col, table_col = st.columns([2, 1])

    with chart_col:
        st.altair_chart(
            horizontal_bar(felt_impact, "country", "avg_felt_intensity", height=520),
            use_container_width=True,
        )

    with table_col:
        st.dataframe(felt_impact, hide_index=True, height=520)

    st.caption(
        "Average CDI (community determined intensity) from public Did You "
        "Feel It reports. Countries with fewer than five felt events are "
        "hidden, and events with no public reports are excluded rather "
        "than treated as zero impact. Sorting reorders the top twenty by "
        "intensity, it does not bring in other countries."
    )


def render_trend(start_date, end_date, countries):
    """Question 3: significant earthquakes over time."""
    st.header("⚡ How has the number of significant earthquakes changed each year?")

    significant = queries.get_significant_by_year(start_date, end_date, countries)

    chart_col, table_col = st.columns([2, 1])

    with chart_col:
        # The year is a number, so it sorts correctly without any help.
        st.bar_chart(significant, x="year", y="significant_events", height=360)

    with table_col:
        st.dataframe(
            significant.rename(columns={"pct_significant": "% significant"}),
            hide_index=True,
            height=360,
        )

    st.caption(
        f"Events at magnitude {SIGNIFICANT_MAGNITUDE} and above, by year. "
        "Kept in chronological order rather than ranked, since the point is "
        "the trend. A partial year at either end of the range will look "
        "lower than a full one."
    )


def render_impact(start_date, end_date, countries):
    """Supplementary: recorded human cost."""
    st.header("💀 Where do earthquakes cost the most lives?")

    st.info(
        "This section reads a different source from the rest of the "
        "dashboard. NCEI records only damaging earthquakes, around 1,500 "
        "since 2000 against 186,000 in the USGS catalog, but unlike USGS "
        "it says how many people died.",
        icon="ℹ️",
    )

    impact = queries.get_impact_by_country(start_date, end_date, countries)

    if impact.empty:
        st.info("No countries with recorded deaths match these filters.")
    else:
        impact_sort = st.radio(
            "Sort by",
            SORT_OPTIONS,
            horizontal=True,
            key="impact_sort",
        )
        impact = sort_ranking(impact, "deaths_per_million", "country", impact_sort)

        chart_col, table_col = st.columns([2, 1])

        with chart_col:
            st.altair_chart(
                horizontal_bar(impact, "country", "deaths_per_million", height=520),
                use_container_width=True,
            )

        with table_col:
            st.dataframe(impact, hide_index=True, height=520)

        st.caption(
            f"Deaths per million residents, for countries with at least "
            f"{MIN_DEATHS_FOR_RANKING} recorded deaths. Both numerator and "
            "denominator are people here, so the ratio compares how "
            "deadly earthquakes have been relative to how many live "
            "there. A small country with one catastrophe can top this "
            "list on a single event, which is worth reading alongside "
            "the event count."
        )

    st.subheader("🔟 Deadliest individual earthquakes")

    deadliest = queries.get_deadliest_events(start_date, end_date, countries)

    if deadliest.empty:
        st.info("No individual events with recorded deaths match these filters.")
    else:
        st.dataframe(deadliest, hide_index=True, use_container_width=True)
        st.caption(
            "Death tolls include losses from secondary effects such as "
            "tsunami. Damage figures are recorded for only about 18% of "
            "events, so a blank there means no figure was published, not "
            "that there was no damage."
        )

def render_distribution(start_date, end_date, countries):
    """Supplementary: magnitude and depth bands."""
    st.header("📏 Magnitude and depth distribution")

    left, right = st.columns(2)

    with left:
        st.subheader("By magnitude band")
        magnitudes = queries.get_magnitude_bands(start_date, end_date, countries)
        st.altair_chart(
            vertical_bar(
                magnitudes, "magnitude_category", "events", MAGNITUDE_BAND_ORDER
            ),
            use_container_width=True,
        )

    with right:
        st.subheader("By depth band")
        depths = queries.get_depth_bands(start_date, end_date, countries)
        st.altair_chart(
            vertical_bar(depths, "depth_category", "events", DEPTH_BAND_ORDER),
            use_container_width=True,
        )

    st.caption(
        "Bands are kept in their natural order rather than ranked, since "
        "the sequence is the point. Thresholds follow the conventional "
        "seismological bands rather than anything derived from this dataset."
    )

def render_explore(start_date, end_date, countries):
    """
    Supplementary: an open ended view of the impact records.

    Everything else on this dashboard answers a fixed question. This
    section does not: the reader picks the axes and the value. The
    dropdowns are split by type, so a numeric column is never offered as
    an axis and a categorical one is never offered as the cell value.
    """
    st.header("🔎 Explore the impact records")

    st.info(
        "Built on the NCEI records, meaning damaging earthquakes only. "
        "Deaths are recorded for about 41% of them and damage for about "
        "18%, so an empty cell usually means no figure was published, "
        "not that the value was zero.",
        icon="ℹ️",
    )

    events = queries.get_impact_events(start_date, end_date, countries)

    if events.empty:
        st.info("No events match these filters.")
        return

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        x_label = st.selectbox(
            "X axis", list(EXPLORE_CATEGORICAL), index=0, key="explore_heat_x"
        )
    with col2:
        y_label = st.selectbox(
            "Y axis", list(EXPLORE_CATEGORICAL), index=1, key="explore_heat_y"
        )
    with col3:
        value_label = st.selectbox(
            "Value", list(EXPLORE_NUMERIC), index=2, key="explore_heat_value"
        )
    with col4:
        agg_label = st.selectbox(
            "Aggregation", list(EXPLORE_AGGREGATIONS), index=0, key="explore_heat_agg"
        )

    x_column = EXPLORE_CATEGORICAL[x_label]
    y_column = EXPLORE_CATEGORICAL[y_label]
    value_column = EXPLORE_NUMERIC[value_label]
    agg = EXPLORE_AGGREGATIONS[agg_label]

    if x_column == y_column:
        st.info("Pick two different columns for the axes.")
        return

    grouped = _aggregate(events, [x_column, y_column], value_column, agg)

    if grouped.empty:
        st.info("No events have a figure for that combination.")
        return

    st.altair_chart(
        explore_heatmap(
            grouped, x_column, y_column, value_column,
            x_label, y_label, f"{agg_label} {value_label.lower()}",
            x_order=BAND_ORDERS.get(x_column),
            y_order=BAND_ORDERS.get(y_column),
        ),
        use_container_width=True,
    )
    st.caption(
        "Cells are empty where no event falls in that combination, and "
        "also where events fall there but carry no figure for the chosen "
        "value. Picking Event count as the value shows which of the two "
        "is happening."
    )
def _aggregate(events, group_columns, value_column, agg):
    """
    Group and aggregate, keeping nulls out of the arithmetic.

    Event count is the exception: it counts rows that have a figure for
    the chosen column, which is what makes coverage visible rather than
    hidden.
    """
    data = events.dropna(subset=group_columns + [value_column])

    if data.empty:
        return data

    grouped = data.groupby(group_columns, observed=True)[value_column]
    result = grouped.count() if agg == "count" else grouped.agg(agg)

    return result.reset_index()