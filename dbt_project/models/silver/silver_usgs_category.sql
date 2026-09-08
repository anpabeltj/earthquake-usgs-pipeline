/*
    Bin the numeric measures into readable categories.

    Grain matches silver_usgs_cleaned, one row per event. Thresholds
    follow the conventional seismological bands rather than anything
    derived from this dataset, so they stay meaningful regardless of how
    much history has been loaded.
*/

with cleaned as (

    select * from {{ ref('silver_usgs_cleaned') }}

),

categorized as (

    select
        usgs_id,

        {{ categorize_magnitude('magnitude') }} as magnitude_category,

        {{ categorize_depth('depth_km') }} as depth_category,

        coalesce(alert, 'none') as alert_level

    from cleaned

)

select * from categorized