{{
    config(
        materialized = 'incremental',
        unique_key = 'usgs_id',
        incremental_strategy = 'merge'
    )
}}

/*
    Cast and deduplicate the raw USGS catalog.

    The same event can appear several times in bronze: once from the
    backfill, again from an overlapping hourly window, and again after
    USGS revises it. The qualify clause keeps the copy with the highest
    updated_ms, which is USGS's own marker of the latest revision. Using
    ingestion time instead would sometimes keep an older revision that
    simply happened to be fetched later.

    On incremental runs only recent source partitions are scanned. The
    backfill loads everything once, and after that only the trailing
    window changes.
*/

with source as (

    select *
    from {{ source('bronze', 'bronze_usgs_earthquake') }}

    {% if is_incremental() %}
    where _source_date >= date_sub(current_date(), interval 7 day)
    {% endif %}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by usgs_id
        order by updated_ms desc
    ) = 1

),

cleaned as (

    select
        usgs_id,

        -- USGS reports epoch milliseconds, BigQuery wants microseconds.
        timestamp_millis(event_time_ms) as event_time,
        timestamp_millis(updated_ms) as updated_at,

        magnitude,
        magnitude_type,
        depth_km,
        latitude,
        longitude,

        felt_reports,
        cdi,
        mmi,

        -- PAGER only assesses events likely to cause damage, so a null
        -- here means not assessed rather than no risk.
        alert,

        tsunami_flag,
        significance,
        station_count,
        azimuthal_gap,
        network,
        status,
        event_type,
        place as raw_place

    from deduplicated

)

select * from cleaned
