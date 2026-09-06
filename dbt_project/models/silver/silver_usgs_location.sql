/*
    Parse the free text place field into structured columns.

    USGS writes it in several shapes:

        "95 km W of Petrolia, CA"          distance, direction, place, region
        "2 km NNW of Astros, Greece"       same, region is a country
        "Japan region"                     country name with a suffix
        "Southwest Indian Ridge"           region only, no nearby land

    The region segment is a country for most of the world but a US state
    for events inside the United States, which is why the seed has to
    carry both.

    Place names contain accented characters such as Astros and Pahala,
    so nothing here uppercases or strips characters beyond trimming.
*/

with cleaned as (

    select
        usgs_id,
        raw_place
    from {{ ref('silver_usgs_cleaned') }}

),

extracted as (

    select
        usgs_id,
        raw_place,

        cast(regexp_extract(raw_place, r'^(\d+)\s*km\s') as int64) as distance_km,

        -- Compass codes run one to three letters, for example N, NE, ENE.
        regexp_extract(raw_place, r'^\d+\s*km\s+([NSEW]{1,3})\s+of\s') as direction,

        -- Everything after "of" when the distance form is used, and the
        -- whole string otherwise.
        coalesce(
            regexp_extract(raw_place, r'^\d+\s*km\s+[NSEW]{1,3}\s+of\s+(.+)$'),
            raw_place
        ) as remainder

    from cleaned

),

split_region as (

    select
        usgs_id,
        raw_place,
        distance_km,
        direction,
        remainder,

        -- The region is the segment after the last comma. Ocean events
        -- have no comma at all, so there is nothing to split.
        case
            when strpos(remainder, ',') > 0
                then trim(array_reverse(split(remainder, ','))[safe_offset(0)])
            else trim(remainder)
        end as region_raw,

        case
            when strpos(remainder, ',') > 0
                then trim(regexp_extract(remainder, r'^(.*),[^,]*$'))
            else null
        end as nearest_place

    from extracted

),

matchable as (

    select
        split_region.*,

        -- Two shapes stop a real country name from matching the seed.
        --
        -- USGS appends " region" to some names, "Japan region" and
        -- "Fiji region", which between them account for several
        -- thousand events that would otherwise have no country at all.
        -- Note what this asserts: USGS uses that suffix for events near
        -- or offshore of a country, not necessarily inside its borders,
        -- so attributing them to that country is a judgement rather
        -- than something the source states. It is a narrower judgement
        -- than mapping a sea name would be, since the country is named
        -- outright, but it is still one.
        --
        -- Hyphens are the other shape. USGS writes "Timor Leste" where
        -- country_converter writes "Timor-Leste", and the same applies
        -- to Guinea-Bissau. Flattening the hyphen on both sides costs
        -- nothing and asserts nothing.
        replace(
            regexp_replace(lower(trim(region_raw)), r'\s+region$', ''),
            '-',
            ' '
        ) as region_key

    from split_region

),

with_country as (

    select
        matchable.usgs_id,
        matchable.direction,
        matchable.distance_km,
        matchable.nearest_place,
        matchable.region_raw,
        mapping.country,
        mapping.iso3,
        mapping.continent
    from matchable
    left join {{ ref('seed_region_country') }} as mapping
        on matchable.region_key = replace(lower(trim(mapping.region)), '-', ' ')

)

select
    usgs_id,
    direction,
    distance_km,
    nearest_place,
    region_raw,
    country,
    iso3,
    continent
from with_country