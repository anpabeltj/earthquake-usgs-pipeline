/*
    Location dimension.

    Coordinates deliberately live in the fact table, not here. They are
    unique to each event, so keeping them in the dimension would make it
    as large as the fact and defeat the point. What stays here is the
    part that repeats across thousands of events: the nearby place, the
    region, and where in the world that sits.

    Country and continent are null for events in international waters.
    USGS names those after seismic regions such as "Southwest Indian
    Ridge", which no country owns, so there is nothing to map them to
    and the region name is used on its own instead.

    The surrogate key is built from lowercased values. USGS is not
    consistent about capitalisation, writing "Southwest Indian Ridge"
    with a capital and "southeast Indian Ridge" without, so keying on
    the raw text would split one place into two dimension rows and cut
    its event count in half. Grouping on the lowered form and taking one
    spelling for display keeps that from happening.
*/

with parsed as (

    select
        nearest_place,
        region_raw,
        country,
        iso3,
        continent
    from {{ ref('silver_usgs_location') }}

),

grouped as (

    select
        lower(trim(coalesce(nearest_place, ''))) as nearest_place_key,
        lower(trim(coalesce(region_raw, ''))) as region_key,

        max(nearest_place) as nearest_place,
        max(region_raw) as region,

        max(country) as country,
        max(iso3) as iso3,
        max(continent) as continent

    from parsed
    group by nearest_place_key, region_key

)

select
    {{ dbt_utils.generate_surrogate_key(['nearest_place_key', 'region_key']) }} as location_id,
    nearest_place,
    region,
    country,
    iso3,
    continent
from grouped
