-- ================================================================
-- One time setup for the USGS earthquake pipeline
--
-- Run once in the BigQuery console before the first DAG run.
-- Set the query processing location to asia-southeast2 first.
--
-- Silver and gold tables are not created here. dbt builds those.
-- ================================================================


-- ----------------------------------------------------------------
-- Datasets
--
-- bronze, silver, and gold are the medallion layers. ops holds
-- pipeline state that is neither raw data nor analytics.
-- ----------------------------------------------------------------

CREATE SCHEMA IF NOT EXISTS `earthquake-final-de.bronze`
OPTIONS (location = 'asia-southeast2');

CREATE SCHEMA IF NOT EXISTS `earthquake-final-de.silver`
OPTIONS (location = 'asia-southeast2');

CREATE SCHEMA IF NOT EXISTS `earthquake-final-de.gold`
OPTIONS (location = 'asia-southeast2');

CREATE SCHEMA IF NOT EXISTS `earthquake-final-de.ops`
OPTIONS (location = 'asia-southeast2');


-- ----------------------------------------------------------------
-- bronze_usgs_earthquake
--
-- Types are kept as USGS sent them. The API returns numbers as
-- numbers, so storing them as text would add a transformation rather
-- than avoid one.
--
-- Partitioned on _source_date, the window a run was asked to load,
-- not the event date. It is metadata about the load, which makes
-- clearing and replaying one backfill window straightforward.
-- ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `earthquake-final-de.bronze.bronze_usgs_earthquake` (
    usgs_id               STRING     OPTIONS (description = 'USGS event id, unique per event'),
    magnitude             FLOAT64    OPTIONS (description = 'Preferred magnitude'),
    place                 STRING     OPTIONS (description = 'Free text location description'),
    event_time_ms         INT64      OPTIONS (description = 'Event time, epoch milliseconds'),
    updated_ms            INT64      OPTIONS (description = 'Last revision time, epoch milliseconds'),
    felt_reports          INT64      OPTIONS (description = 'Number of Did You Feel It responses'),
    cdi                   FLOAT64    OPTIONS (description = 'Community determined intensity'),
    mmi                   FLOAT64    OPTIONS (description = 'Instrumental intensity from ShakeMap'),
    alert                 STRING     OPTIONS (description = 'PAGER alert level, null when not assessed'),
    status                STRING     OPTIONS (description = 'automatic or reviewed'),
    tsunami_flag          INT64      OPTIONS (description = '1 when the event is flagged for tsunami'),
    significance          INT64      OPTIONS (description = 'USGS significance score'),
    network               STRING     OPTIONS (description = 'Reporting network code'),
    station_count         INT64      OPTIONS (description = 'Stations used in the solution'),
    azimuthal_gap         FLOAT64    OPTIONS (description = 'Largest azimuthal gap between stations'),
    rms                   FLOAT64    OPTIONS (description = 'Root mean square travel time residual'),
    magnitude_type        STRING     OPTIONS (description = 'How magnitude was measured, mb ml md mww'),
    event_type            STRING     OPTIONS (description = 'earthquake, quarry blast, explosion, ice quake'),
    contributing_ids      STRING     OPTIONS (description = 'Comma separated ids from every reporting network'),
    contributing_sources  STRING     OPTIONS (description = 'Comma separated network codes'),
    product_types         STRING     OPTIONS (description = 'Comma separated products such as dyfi and shakemap'),
    longitude             FLOAT64    OPTIONS (description = 'Epicentre longitude'),
    latitude              FLOAT64    OPTIONS (description = 'Epicentre latitude'),
    depth_km              FLOAT64    OPTIONS (description = 'Depth in kilometres'),
    _ingested_at          TIMESTAMP  OPTIONS (description = 'When the pipeline wrote this row'),
    _source_date          DATE       OPTIONS (description = 'Start of the window this run was asked to load')
)
PARTITION BY _source_date
OPTIONS (
    description = 'Raw USGS catalog events. Append only, revised events appear more than once.'
);


-- ----------------------------------------------------------------
-- notification_log
--
-- Records which earthquakes have already been announced on Telegram.
-- The alert task reads this to decide what is new, which is what makes
-- a retried run safe to repeat.
--
-- Not managed by dbt. It is pipeline state, not a transformation.
-- ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `earthquake-final-de.ops.notification_log` (
    usgs_id      STRING     NOT NULL OPTIONS (description = 'Matches gold_fact_earthquake.usgs_id'),
    notified_at  TIMESTAMP  DEFAULT CURRENT_TIMESTAMP() OPTIONS (description = 'When the alert was sent')
)
OPTIONS (
    description = 'Earthquakes already announced on Telegram. Prevents duplicate alerts.'
);

-- ----------------------------------------------------------------
-- bronze_worldbank_population
--
-- Total population per country per year, from the World Bank
-- Indicators API (SP.POP.TOTL). Append only, same as the earthquake
-- bronze table: the World Bank revises past years as national censuses
-- and estimates are updated, so one country year can appear more than
-- once and silver keeps the newest copy.
--
-- population is FLOAT64 rather than INT64 because the API is only
-- documented to return a number, not an integer. Casting happens in
-- silver, where a bad value fails loudly instead of rejecting the whole
-- load job.
--
-- Not partitioned. The whole table is a few thousand rows.
-- ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `earthquake-final-de.bronze.bronze_worldbank_population` (
    iso3          STRING     OPTIONS (description = 'ISO 3166-1 alpha-3 country code'),
    country_name  STRING     OPTIONS (description = 'Country name as written by the World Bank'),
    year          INT64      OPTIONS (description = 'Observation year'),
    population    FLOAT64    OPTIONS (description = 'Total population, null when not yet published'),
    _ingested_at  TIMESTAMP  OPTIONS (description = 'When the pipeline wrote this row')
)
OPTIONS (
    description = 'Raw World Bank population indicator. Append only, revised years appear more than once.'
);

-- ----------------------------------------------------------------
-- bronze_ncei_earthquake
--
-- NCEI/WDS Global Significant Earthquake Database. Where USGS records
-- every event above the magnitude threshold, this holds only the ones
-- that did damage: a death, roughly a million dollars of damage,
-- magnitude 7.5 and up, MMI X and up, or a tsunami. Around 1,472
-- events fall in the 2000 to present window the pipeline covers,
-- against 186 thousand in bronze_usgs_earthquake.
--
-- That is the point of the source. USGS answers where earthquakes
-- happen, NCEI answers what they cost.
--
-- Types are kept as the API sent them, including the split date parts.
-- Assembling a timestamp from year, month, day, hour, minute and
-- second is a transformation, so it belongs in silver where a bad
-- value fails loudly instead of rejecting the whole load job.
--
-- The AmountOrder columns are order of magnitude codes, 1 to 4, used
-- when the exact figure is unknown. They are kept here for
-- completeness but should not be mixed with the exact counts.
--
-- Append only, same as the other bronze tables. NCEI revises death
-- tolls and damage figures as reports come in, so one event can appear
-- more than once and silver keeps the newest copy.
--
-- Not partitioned. The whole table is under two thousand rows.
--
-- Cite as: National Geophysical Data Center / World Data Service
-- (NGDC/WDS): NCEI/WDS Global Significant Earthquake Database. NOAA
-- National Centers for Environmental Information.
-- doi:10.7289/V5TD9V7K
-- ----------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `earthquake-final-de.bronze.bronze_ncei_earthquake` (
    ncei_id                          INT64      OPTIONS (description = 'NCEI event id, unique per event'),
    year                             INT64      OPTIONS (description = 'Event year'),
    month                            INT64      OPTIONS (description = 'Event month, null when not recorded'),
    day                              INT64      OPTIONS (description = 'Event day, null when not recorded'),
    hour                             INT64      OPTIONS (description = 'Event hour UTC, null when not recorded'),
    minute                           INT64      OPTIONS (description = 'Event minute, null when not recorded'),
    second                           FLOAT64    OPTIONS (description = 'Event second, fractional'),

    location_name                    STRING     OPTIONS (description = 'Free text location, uppercase, country first'),
    country                          STRING     OPTIONS (description = 'Country as written by NCEI, uppercase'),
    area                             STRING     OPTIONS (description = 'Subdivision code where present, for example PR'),
    region_code                      INT64      OPTIONS (description = 'NCEI internal region code'),
    latitude                         FLOAT64    OPTIONS (description = 'Epicentre latitude, decimal degrees'),
    longitude                        FLOAT64    OPTIONS (description = 'Epicentre longitude, decimal degrees'),

    eq_depth                         FLOAT64    OPTIONS (description = 'Focal depth, kilometres'),
    eq_magnitude                     FLOAT64    OPTIONS (description = 'Primary magnitude'),
    eq_mag_mw                        FLOAT64    OPTIONS (description = 'Moment magnitude'),
    eq_mag_ms                        FLOAT64    OPTIONS (description = 'Surface wave magnitude'),
    eq_mag_mb                        FLOAT64    OPTIONS (description = 'Body wave magnitude'),
    eq_mag_ml                        FLOAT64    OPTIONS (description = 'Local magnitude'),
    eq_mag_unk                       FLOAT64    OPTIONS (description = 'Magnitude of unknown type'),
    intensity                        INT64      OPTIONS (description = 'Maximum Modified Mercalli Intensity'),

    deaths                           INT64      OPTIONS (description = 'Recorded deaths from the earthquake itself'),
    injuries                         INT64      OPTIONS (description = 'Recorded injuries'),
    damage_millions_dollars          FLOAT64    OPTIONS (description = 'Recorded damage, millions of US dollars'),
    houses_destroyed                 INT64      OPTIONS (description = 'Houses destroyed'),
    houses_damaged                   INT64      OPTIONS (description = 'Houses damaged'),

    deaths_total                     INT64      OPTIONS (description = 'Deaths including secondary effects, meaning to be confirmed against the data'),
    injuries_total                   INT64      OPTIONS (description = 'Injuries including secondary effects'),
    damage_millions_dollars_total    FLOAT64    OPTIONS (description = 'Damage including secondary effects'),
    houses_destroyed_total           INT64      OPTIONS (description = 'Houses destroyed including secondary effects'),
    houses_damaged_total             INT64      OPTIONS (description = 'Houses damaged including secondary effects'),

    deaths_amount_order              INT64      OPTIONS (description = 'Order of magnitude code 1 to 4, used when the exact count is unknown'),
    injuries_amount_order            INT64      OPTIONS (description = 'Order of magnitude code for injuries'),
    damage_amount_order              INT64      OPTIONS (description = 'Order of magnitude code for damage'),
    houses_destroyed_amount_order    INT64      OPTIONS (description = 'Order of magnitude code for houses destroyed'),
    houses_damaged_amount_order      INT64      OPTIONS (description = 'Order of magnitude code for houses damaged'),

    tsunami_event_id                 INT64      OPTIONS (description = 'Link to the NCEI tsunami database when the event caused one'),
    volcano_event_id                 INT64      OPTIONS (description = 'Link to the NCEI volcano database when the event is volcanic'),

    _ingested_at                     TIMESTAMP  OPTIONS (description = 'When the pipeline wrote this row')
)
OPTIONS (
    description = 'Raw NCEI significant earthquake records. Damaging events only, append only, revised events appear more than once.'
);