"""
Chart builders and the sorting they depend on.

Charts with a text axis are drawn with Altair rather than st.bar_chart.
st.bar_chart sorts a categorical axis alphabetically and ignores both
DataFrame row order and pandas Categorical ordering, so a sorted ranking
still lands on screen in alphabetical order. Altair takes an explicit
sort list, which is the only thing that holds.

Charts whose axis is numeric (hour of day, year) stay on st.bar_chart,
since numbers already sort correctly.
"""

import altair as alt

from config import SORT_HIGH, SORT_LOW


def axis_title(column_name):
    """Turn a column name into something readable on an axis."""
    return column_name.replace("_", " ")


def sort_ranking(df, value_column, label_column, choice):
    """
    Order a ranking table by the user's choice.

    This reorders the rows the query already returned. It does not pull
    in different rows, so "Lowest first" shows the bottom of the top
    twenty, not the bottom of the whole catalog.
    """
    if choice == SORT_HIGH:
        return df.sort_values(value_column, ascending=False)
    if choice == SORT_LOW:
        return df.sort_values(value_column, ascending=True)
    return df.sort_values(label_column)


def horizontal_bar(df, label_column, value_column, height=320):
    """
    Horizontal bars in the order the DataFrame is already in.

    The sort list is taken from the rows as they arrive, so whatever
    sort_ranking decided is what reaches the screen. On a y axis the
    first entry in that list is drawn at the top, so no reversing is
    needed.
    """
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{value_column}:Q", title=axis_title(value_column)),
            y=alt.Y(f"{label_column}:N", title=None, sort=df[label_column].tolist()),
            tooltip=list(df.columns),
        )
        .properties(height=height)
    )


def vertical_bar(df, label_column, value_column, order, height=300):
    """
    Vertical bars in a fixed order.

    Used for the magnitude and depth bands, where the sequence is
    meaningful and fixed rather than something the reader chooses.
    """
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{label_column}:N", title=axis_title(label_column), sort=order),
            y=alt.Y(f"{value_column}:Q", title=axis_title(value_column)),
            tooltip=list(df.columns),
        )
        .properties(height=height)
    )


def monthly_line(df, height=280):
    """
    Events over time.

    The month stays a real date on a temporal axis rather than being
    formatted into "Feb 2026" text. A text axis would be sorted
    alphabetically, which scrambles a timeline; a temporal one is always
    chronological.
    """
    return (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("month:T", title="month", axis=alt.Axis(format="%b %Y")),
            y=alt.Y("events:Q", title="events"),
            tooltip=[
                alt.Tooltip("month:T", format="%b %Y"),
                alt.Tooltip("events:Q"),
            ],
        )
        .properties(height=height)
    )
def explore_scatter(df, x_column, y_column, x_label, y_label, log_y, height=460):
    """
    Two numeric columns against each other, one point per event.

    No trend line. Fitting one would suggest the y value can be read off
    the x, and for the pairing readers reach for most, magnitude against
    deaths, the correlation is 0.39. The spread is the finding.
    """
    y_scale = alt.Scale(type="log") if log_y else alt.Scale(zero=False)

    return (
        alt.Chart(df)
        .mark_circle(size=70, opacity=0.6)
        .encode(
            x=alt.X(f"{x_column}:Q", title=x_label, scale=alt.Scale(zero=False)),
            y=alt.Y(f"{y_column}:Q", title=y_label, scale=y_scale),
            color=alt.Color(
                "caused_tsunami:N",
                title="caused tsunami",
                scale=alt.Scale(range=["#7c8cf8", "#e5484d"]),
            ),
            tooltip=[
                alt.Tooltip("event_date:T", title="date"),
                alt.Tooltip("location_name:N", title="location"),
                alt.Tooltip(f"{x_column}:Q", title=x_label),
                alt.Tooltip(f"{y_column}:Q", title=y_label, format=","),
            ],
        )
        .properties(height=height)
    )


def explore_heatmap(df, x_column, y_column, value_column, x_label, y_label, value_label,
                    x_order=None, y_order=None, height=400):
    """
    Two categorical axes with a numeric value in the cell colour.

    Sort orders are passed in for the band columns so magnitude reads
    Minor to Major rather than alphabetically.
    """
    return (
        alt.Chart(df)
        .mark_rect()
        .encode(
            x=alt.X(f"{x_column}:N", title=x_label, sort=x_order),
            y=alt.Y(f"{y_column}:N", title=y_label, sort=y_order),
            color=alt.Color(
                f"{value_column}:Q",
                title=value_label,
                scale=alt.Scale(scheme="reds"),
            ),
            tooltip=[
                alt.Tooltip(f"{x_column}:N", title=x_label),
                alt.Tooltip(f"{y_column}:N", title=y_label),
                alt.Tooltip(f"{value_column}:Q", title=value_label, format=","),
            ],
        )
        .properties(height=height)
    )


def explore_bar(df, label_column, value_column, label_text, value_label, height=460):
    """One categorical axis with an aggregated numeric value."""
    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{value_column}:Q", title=value_label),
            y=alt.Y(f"{label_column}:N", title=None, sort=df[label_column].tolist()),
            tooltip=[
                alt.Tooltip(f"{label_column}:N", title=label_text),
                alt.Tooltip(f"{value_column}:Q", title=value_label, format=","),
            ],
        )
        .properties(height=height)
    )