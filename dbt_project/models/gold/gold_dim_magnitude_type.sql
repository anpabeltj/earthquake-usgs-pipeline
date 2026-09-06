/*
    How the magnitude was measured.

    Different scales suit different sizes and distances, so comparing a
    body wave magnitude against a moment magnitude without knowing which
    is which can mislead. Derived from the data rather than hardcoded,
    since USGS adds scales over time.

    A small share of events carry no magnitude type at all. Those are
    coalesced to 'unknown' here, matching gold_fact_earthquake, so every
    event resolves to a real row in this dimension instead of an
    orphaned foreign key.
*/

with observed as (

    select distinct coalesce(magnitude_type, 'unknown') as magnitude_type
    from {{ ref('silver_usgs_cleaned') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['magnitude_type']) }} as magnitude_type_id,
    magnitude_type
from observed