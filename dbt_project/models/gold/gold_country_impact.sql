{{ config(materialized = 'table') }}

/*
    Recorded earthquake impact per country per year, with that
    country's population alongside.

    This replaces gold_country_exposure, which divided earthquake
    counts by population. That ratio was wrong: the numerator was
    geological events and the denominator was people, so it measured
    nothing. Japan came out above Indonesia despite Indonesia recording
    more earthquakes and having more than twice the population.

    Deaths per million residents is a different thing. Numerator and
    denominator are both people, which is how casualty rates are
    normally expressed, and the comparison it invites is a real one:
    earthquakes of similar size kill very different numbers of people
    depending on building stock and preparedness.

    ## What the figures cover

    Only NCEI events reach this table, meaning earthquakes that caused
    a death, roughly a million dollars of damage, magnitude 7.5 and up,
    MMI X and up, or a tsunami. The 186 thousand events in the USGS
    catalog are not counted here, and should not be: this table is
    about cost, not about how often the ground moves.

    Coverage within NCEI is uneven, and the columns say so:
    events_with_deaths and events_with_damage report how many events in
    each country year actually carry a figure. Deaths are present for
    about 41% of events and damage for about 18%, so a country total is
    a floor, not a full accounting. Summing damage across countries and
    calling it the cost of earthquakes would overstate what the data
    supports.

    ## Population

    Joined on ISO3, not on name. NCEI writes "USA" and "UK" where
    country_converter writes "United States" and "United Kingdom", and
    World Bank writes "Russian Federation" where the seed writes
    "Russia". Text matching would drop rows silently.

    The current year's population is usually unpublished while the
    year's earthquakes already exist, so those rows fall back to the
    latest available year and population_estimated marks every one.

    29 of 1,472 events resolve to no country at all: the ambiguous
    "CONGO", distant dependencies, and open ocean. They are absent from
    this table by design, which is why a global total taken from here
    will fall slightly short of one taken from gold_earthquake_impact.
*/

with impact as (

    select
        iso3,
        country,
        continent,
        year,
        count(*) as events,
        countif(deaths is not null) as events_with_deaths,
        countif(damage_millions_dollars is not null) as events_with_damage,
        countif(caused_tsunami) as events_with_tsunami,
        sum(deaths) as deaths,
        sum(injuries) as injuries,
        sum(damage_millions_dollars) as damage_millions_dollars,
        sum(houses_destroyed) as houses_destroyed,
        max(eq_magnitude) as max_magnitude
    from {{ ref('gold_earthquake_impact') }}
    where iso3 is not null
      and iso3 != ''
    group by iso3, country, continent, year

),

population_by_year as (

    select
        iso3,
        year,
        population as yearly_population
    from {{ ref('silver_population') }}

),

population_latest as (

    select
        iso3,
        yearly_population as latest_population
    from population_by_year
    qualify row_number() over (
        partition by iso3
        order by year desc
    ) = 1

),

joined as (

    select
        impact.*,
        coalesce(
            population_by_year.yearly_population,
            population_latest.latest_population
        ) as population,
        population_by_year.yearly_population is null as population_estimated
    from impact
    left join population_by_year
        on impact.iso3 = population_by_year.iso3
       and impact.year = population_by_year.year
    left join population_latest
        on impact.iso3 = population_latest.iso3

)

select
    iso3,
    country,
    continent,
    year,

    events,
    events_with_deaths,
    events_with_damage,
    events_with_tsunami,

    deaths,
    injuries,
    damage_millions_dollars,
    houses_destroyed,
    max_magnitude,

    population,
    population_estimated,

    case
        when population > 0 and deaths is not null
            then round(deaths / population * 1000000, 2)
    end as deaths_per_million

from joined