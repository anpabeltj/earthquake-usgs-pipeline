{% snapshot earthquake_snapshot %}
{{
    config(
      target_schema='gold',
      unique_key='usgs_id',
      strategy='check',
      check_cols=[
        'magnitude',
        'magnitude_type',
        'depth_km',
        'latitude',
        'longitude',
        'status',
        'felt_reports',
        'cdi',
        'mmi',
        'alert',
        'significance',
      ],
    )
}}

/*
    Full revision history of every earthquake, not just the latest
    version.

    silver_usgs_cleaned keeps only the newest updated_at per usgs_id,
    which is right for the fact table but throws away every prior
    version. USGS revises events long after they happen: the 2004
    Sumatra event carries an updated timestamp from 2026, and the
    magnitude 7.8 Flores event of August 2026 was still being revised
    three weeks later.

    strategy='check' rather than 'timestamp', which is what this
    started as. USGS bumps updated on an event every six hours or so
    even when nothing in the solution changes, apparently as products
    like ShakeMap and DYFI are regenerated. Measured across the first
    18 superseded rows this snapshot produced: magnitude changed 0
    times, depth twice, felt reports five times, and 11 rows recorded
    no change at all. Comparing the columns themselves keeps those
    empty touches out.

    The listed columns are the ones worth tracking. usgs_id, event_time
    and raw_place identify the event rather than describe it, and
    updated_at is exactly the field that moves without meaning
    anything.

    dbt adds dbt_scd_id, dbt_updated_at, dbt_valid_from and
    dbt_valid_to. A row with dbt_valid_to = null is the current
    version. usgs_id is not unique here, dbt_scd_id is.
*/

select * from {{ ref('silver_usgs_cleaned') }}

{% endsnapshot %}