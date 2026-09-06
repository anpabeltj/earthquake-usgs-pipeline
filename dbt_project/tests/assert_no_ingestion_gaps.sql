/*
    Fail when a calendar day inside the loaded window holds no events.

    USGS records around 14 earthquakes a day worldwide at magnitude 4.5
    and above, so a day with none is not a quiet day, it is a day that
    was never ingested.

    This exists because that happened. usgs_backfill runs monthly and
    stopped at the end of July; usgs_pipeline started on 30 August with
    a two day lookback. Nothing covered 2 to 27 August, and the gap went
    unnoticed through every other test, because tests check the rows
    that are there, not the ones that should be. It surfaced only when
    NCEI reported a magnitude 7.8 event that killed 105 people and no
    matching USGS event could be found.

    The first and last day of the window are excluded, since a partial
    day at either edge is expected rather than a fault.
*/

with bounds as (

    select
        min(event_date) as first_date,
        max(event_date) as last_date
    from {{ ref('gold_fact_earthquake') }}

),

calendar as (

    select day
    from bounds,
    unnest(generate_date_array(first_date, last_date)) as day
    where day > (select first_date from bounds)
      and day < (select last_date from bounds)

),

events_per_day as (

    select event_date, count(*) as events
    from {{ ref('gold_fact_earthquake') }}
    group by event_date

)

select
    calendar.day,
    coalesce(events_per_day.events, 0) as events
from calendar
left join events_per_day
    on calendar.day = events_per_day.event_date
where events_per_day.event_date is null