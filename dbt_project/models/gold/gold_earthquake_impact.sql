{{ config(materialized = 'table') }}

/*
    One row per NCEI significant earthquake, with the recorded human
    and economic cost, and a link to the matching USGS event where one
    was found.

    This is the half of the picture the USGS catalog cannot give. USGS
    records every event above magnitude 4.5 and says nothing about what
    it cost; NCEI records only the damaging ones and says how many died
    and what it destroyed. Keeping them in separate tables rather than
    one is deliberate: their grain differs by a factor of 126, and
    forcing them together would leave almost every row empty on the
    impact side.

    ## Matching

    The two sources share no identifier, so events are matched on time
    and distance. The thresholds below are not guesses. Measured across
    the 1,471 NCEI events that carry an exact time, matched against
    USGS with a deliberately loose window of 10 minutes and 200 km:

        median   0 seconds,  0.0 km
        p90      0 seconds,  2.5 km
        p99     28 seconds, 15.2 km
        max    558 seconds, 48.5 km

    More than half the pairs are identical to the second and to the
    decimal, which suggests NCEI takes its event parameters from the
    same solutions USGS publishes. 120 seconds and 50 km sits well
    clear of the p99 while still excluding anything that would be a
    coincidence rather than a match.

    Where several USGS events fall inside the window, the closest is
    taken, then the one nearest in time. usgs_id is null when nothing
    matched, which is honest rather than hidden: about 6% of events
    find no partner, and the dashboard reports that rate rather than
    quietly dropping those rows.

    ## Figures

    deaths and the other counts come from the Total variants in silver,
    which include losses from secondary effects such as tsunami. For
    the 2004 Sumatra event those are the story.

    damage_millions_dollars is present for only about 18% of events, so
    it is carried here but should never be summed as though it covered
    the whole set.
*/

with impact as (

    select * from {{ ref('silver_ncei_impact') }}

),

usgs as (

    select
        usgs_id,
        event_time,
        magnitude,
        latitude,
        longitude
    from {{ ref('silver_usgs_cleaned') }}
    where event_type = 'earthquake'

),

matched as (

    select
        impact.ncei_id,
        usgs.usgs_id,
        usgs.magnitude as usgs_magnitude,
        abs(timestamp_diff(impact.event_time, usgs.event_time, second)) as match_time_diff_sec,
        st_distance(
            st_geogpoint(impact.longitude, impact.latitude),
            st_geogpoint(usgs.longitude, usgs.latitude)
        ) / 1000 as match_distance_km
    from impact
    join usgs
        on abs(timestamp_diff(impact.event_time, usgs.event_time, second)) <= 120
       and st_dwithin(
               st_geogpoint(impact.longitude, impact.latitude),
               st_geogpoint(usgs.longitude, usgs.latitude),
               50000
           )
    where impact.has_exact_time
    qualify row_number() over (
        partition by impact.ncei_id
        order by match_distance_km, match_time_diff_sec
    ) = 1

)

select
    impact.ncei_id,
    matched.usgs_id,

    impact.event_time,
    impact.year,
    date(impact.event_time) as event_date,

    impact.location_name,
    impact.country,
    impact.iso3,
    impact.continent,
    impact.latitude,
    impact.longitude,

    impact.eq_magnitude,
    impact.eq_depth,
    impact.intensity,
    -- Bands for the exploration section. Computed here rather than in
    -- the dashboard so the thresholds match the ones already applied to
    -- the USGS path, and cannot drift apart later.
    {{ categorize_magnitude('impact.eq_magnitude') }} as magnitude_category,
    {{ categorize_depth('impact.eq_depth') }} as depth_category,
    cast(floor(impact.year / 10) * 10 as int64) as decade,

    impact.deaths,
    impact.injuries,
    impact.damage_millions_dollars,
    impact.houses_destroyed,
    impact.houses_damaged,
    impact.caused_tsunami,

    -- Kept so the quality of each match can be inspected, and so the
    -- match rate can be reported rather than assumed.
    matched.match_time_diff_sec,
    matched.match_distance_km,

    -- A large gap between the two catalogues' magnitudes is a sign the
    -- pair may be wrong, even when time and distance agree.
    matched.usgs_magnitude,
    abs(impact.eq_magnitude - matched.usgs_magnitude) as magnitude_diff,

    current_timestamp() as loaded_at

from impact
left join matched
    on impact.ncei_id = matched.ncei_id