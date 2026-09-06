{{
    config(
        materialized = 'incremental',
        unique_key = 'usgs_id',
        incremental_strategy = 'merge',
        partition_by = {
            'field': 'event_date',
            'data_type': 'date',
            'granularity': 'month'
        },
        cluster_by = ['location_id', 'magnitude_category_id']
    )
}}

/*
    Central fact table, one row per earthquake.

    Incremental rather than rebuilt each run. With roughly 180 thousand
    events across 26 years, rewriting the whole table every hour would
    burn far more query time than merging the handful of rows that
    actually changed.

    Foreign keys are computed with the same surrogate key expressions
    the dimensions use rather than joined on. Matching on business
    columns would drop rows wherever a parsed value is null, and several
    parsed columns legitimately are: ocean events have no nearby place,
    and most events carry no PAGER level.

    Only tectonic earthquakes are kept. The catalog also holds quarry
    blasts, explosions, and ice quakes, which would distort any question
    about where and when earthquakes occur.
*/

with cleaned as (

    select * from {{ ref('silver_usgs_cleaned') }}
    where event_type = 'earthquake'

    {% if is_incremental() %}
      and updated_at >= timestamp_sub(current_timestamp(), interval 7 day)
    {% endif %}

),

location as (

    select * from {{ ref('silver_usgs_location') }}

),

category as (

    select * from {{ ref('silver_usgs_category') }}

),

joined as (

    select
        cleaned.usgs_id,
        cleaned.event_time,
        cleaned.magnitude,
        cleaned.magnitude_type,
        cleaned.depth_km,
        cleaned.latitude,
        cleaned.longitude,
        cleaned.felt_reports,
        cleaned.cdi,
        cleaned.mmi,
        cleaned.tsunami_flag,
        cleaned.significance,
        cleaned.station_count,
        cleaned.azimuthal_gap,
        cleaned.network,

        location.nearest_place,
        location.region_raw,
        location.country,
        location.continent,

        category.magnitude_category,
        category.depth_category,
        category.alert_level

    from cleaned
    left join location using (usgs_id)
    left join category using (usgs_id)

)

select
    usgs_id,

    {{ dbt_utils.generate_surrogate_key(['event_time']) }} as time_id,

    -- Lowercased to match gold_dim_location, which groups that way
    -- because USGS capitalises the same region name inconsistently.
    {{ dbt_utils.generate_surrogate_key([
        "lower(trim(coalesce(nearest_place, '')))",
        "lower(trim(coalesce(region_raw, '')))"
    ]) }} as location_id,

    {{ dbt_utils.generate_surrogate_key(['magnitude_category']) }} as magnitude_category_id,
    {{ dbt_utils.generate_surrogate_key(['depth_category']) }} as depth_category_id,
    {{ dbt_utils.generate_surrogate_key(["coalesce(magnitude_type, 'unknown')"]) }} as magnitude_type_id,
    {{ dbt_utils.generate_surrogate_key(['alert_level']) }} as alert_level_id,
    {{ dbt_utils.generate_surrogate_key(["coalesce(network, 'unknown')"]) }} as network_id,

    magnitude,
    depth_km,
    felt_reports,
    cdi,
    mmi,
    significance,
    station_count,
    azimuthal_gap,
    tsunami_flag,

    latitude,
    longitude,

    event_time,
    date(event_time) as event_date,
    current_timestamp() as loaded_at

from joined
