/*
    The network that contributed the preferred solution.

    Useful for explaining geographic bias in the catalog: regional
    networks such as ci in California and ak in Alaska report far more
    small events than the global us network does, simply because their
    instruments are denser.

    A small share of events carry no network at all. Those are
    coalesced to 'unknown' here, matching gold_fact_earthquake, so every
    event resolves to a real row in this dimension instead of an
    orphaned foreign key.
*/

with observed as (

    select distinct coalesce(network, 'unknown') as network
    from {{ ref('silver_usgs_cleaned') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['network']) }} as network_id,
    network
from observed