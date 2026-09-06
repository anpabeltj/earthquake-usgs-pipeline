/*
    PAGER alert level, the USGS estimate of expected impact.

    The "none" member matters. PAGER only assesses events likely to
    cause damage, so most records have no level at all. That is not the
    same as green, which means assessed and expected to be harmless.
*/

with levels as (

    select 'green'  as alert_level union all
    select 'yellow' union all
    select 'orange' union all
    select 'red'    union all
    select 'none'

)

select
    {{ dbt_utils.generate_surrogate_key(['alert_level']) }} as alert_level_id,
    alert_level
from levels
