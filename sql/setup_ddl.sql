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