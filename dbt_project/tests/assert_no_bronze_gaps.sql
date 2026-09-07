/*
    Fail when a calendar day inside the loaded window holds no events
    in bronze.

    Same check as assert_no_ingestion_gaps, one layer earlier. That one
    reads gold, so a gap only surfaces after the whole transformation
    chain has run. This one catches it at the source, where the fix is
    to backfill a date range rather than to rebuild every model.

    Both are kept. If this passes and the gold one fails, the rows
    reached bronze but something downstream dropped them, which is a
    different problem with a different fix.
*/

with events_per_day as (

    select
        date({{ epoch_ms_to_timestamp('event_time_ms') }}) as event_day,
        count(*) as events
    from {{ source('bronze', 'bronze_usgs_earthquake') }}
    group by event_day

),

bounds as (

    select
        min(event_day) as first_day,
        max(event_day) as last_day
    from events_per_day

),

calendar as (

    select day
    from bounds,
    unnest(generate_date_array(first_day, last_day)) as day
    where day > (select first_day from bounds)
      and day < (select last_day from bounds)

)

select
    calendar.day
from calendar
left join events_per_day
    on calendar.day = events_per_day.event_day
where events_per_day.event_day is null