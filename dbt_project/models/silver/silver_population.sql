/*
    Cast and deduplicate the World Bank population indicator.

    The same country year appears more than once in bronze: the whole
    series is refetched on every run, and the World Bank revises past
    years as censuses and estimates are updated. The qualify clause
    keeps the most recently ingested copy, which is the right choice
    here, unlike the earthquake table where USGS supplies its own
    revision marker.

    Rows with no population are dropped. The World Bank publishes the
    current year's row before the figure itself exists, and a null
    population is nothing to carry forward.

    Aggregates such as World and Africa Eastern and Southern are left
    in. They carry ISO3-like codes of their own, which will simply not
    match anything when gold joins on real country codes.
*/

with source as (

    select * from {{ source('bronze', 'bronze_worldbank_population') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by iso3, year
        order by _ingested_at desc
    ) = 1

),

cleaned as (

    select
        iso3,
        country_name,
        year,
        cast(population as int64) as population
    from deduplicated
    where population is not null
      and iso3 is not null
      and iso3 != ''
      and year is not null

)

select * from cleaned