/*
    Clean the NCEI significant earthquake records.

    Three things happen here that bronze deliberately left alone.

    The split date parts become one timestamp. NCEI sends year, month,
    day, hour, minute and second as separate fields, and older records
    omit the smaller ones entirely. Every row in the 2000 onward window
    has at least a date, and 1,471 of 1,472 have an hour, so the
    timestamp is built where the parts allow and left null where they
    do not. Only rows with a timestamp can be matched to USGS later.

    The Total variants are chosen over the base ones. Checked against
    the data: of 598 rows with a death count, 585 have deaths equal to
    deathsTotal, 13 differ, and 10 of those 13 carry a tsunami event
    id. Another 13 rows have deathsTotal with no deaths at all. The
    Total figures therefore include deaths from secondary effects,
    mostly tsunami, and are never smaller. For the 2004 Sumatra event
    the tsunami deaths are the story, so ignoring them would be wrong.

    The country name is resolved to ISO3 through the region seed, so
    NCEI can be joined to World Bank population on a stable code rather
    than on a display name. 29 of 1,472 rows resolve to nothing: the
    ambiguous "CONGO", distant dependencies such as "USA TERRITORY" and
    "KERMADEC ISLANDS (NEW ZEALAND)", and open ocean names. Those keep
    a null country on purpose, the same rule already applied to the
    USGS place text.

    The AmountOrder columns are left in bronze. They are order of
    magnitude codes used when the exact figure is unknown, and mixing
    them with exact counts would produce numbers that look precise and
    are not.

    Deduplicated on ncei_id keeping the most recently ingested copy.
    The whole series is refetched on every run, so one event appears
    once per run, and NCEI revises death tolls as reports come in.
*/

with source as (

    select * from {{ source('bronze', 'bronze_ncei_earthquake') }}

),

deduplicated as (

    select *
    from source
    qualify row_number() over (
        partition by ncei_id
        order by _ingested_at desc
    ) = 1

),

cleaned as (

    select
        ncei_id,

        -- Built only where the parts allow. A row with no month or day
        -- cannot be placed on a timeline and cannot be matched to a
        -- USGS event, so it carries a null rather than a guess.
        case
            when month is not null and day is not null
                then timestamp(datetime(
                    cast(year as int64),
                    cast(month as int64),
                    cast(day as int64),
                    cast(coalesce(hour, 0) as int64),
                    cast(coalesce(minute, 0) as int64),
                    cast(coalesce(floor(second), 0) as int64)
                ))
        end as event_time,

        year,
        month is not null and day is not null and hour is not null as has_exact_time,

        location_name,
        latitude,
        longitude,

        eq_magnitude,
        eq_depth,
        intensity,

        -- Total variants, see the note above.
        deaths_total as deaths,
        injuries_total as injuries,
        damage_millions_dollars_total as damage_millions_dollars,
        houses_destroyed_total as houses_destroyed,
        houses_damaged_total as houses_damaged,

        tsunami_event_id is not null as caused_tsunami,

        country as country_raw,
        area,

        _ingested_at

    from deduplicated

),

with_country as (

    select
        cleaned.* except (country_raw),
        cleaned.country_raw,
        mapping.country,
        mapping.iso3,
        mapping.continent
    from cleaned
    left join {{ ref('seed_region_country') }} as mapping
        on lower(trim(cleaned.country_raw)) = lower(trim(mapping.region))

)

select * from with_country