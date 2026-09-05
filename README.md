# 🌍 Global Earthquake Data Pipeline

An end-to-end data pipeline that answers two questions the sources cannot answer alone: **where earthquakes happen**, and **what they cost**.

USGS records every earthquake above magnitude 4.5 and says nothing about the damage. NOAA's NCEI records only the damaging ones and says how many died. Neither is complete on its own. This pipeline ingests both, reconciles them without a shared identifier, and serves the result through a dashboard and automated alerts.

## 🛠️ Tech Stack

- **Orchestration**: Apache Airflow (Docker) 🐳
- **Transformation**: dbt 🔧
- **Warehouse**: Google BigQuery 🗄️
- **Dashboard**: Streamlit 📊
- **Alerting**: Telegram Bot API 🔔
- **Language**: Python, SQL 🐍

## 📡 Data Sources

### USGS Earthquake Catalog

Documentation: https://earthquake.usgs.gov/fdsnws/event/1/

- Every event at magnitude 4.5 and above, backfilled from 2000
- ~187,000 events
- GeoJSON, no authentication, capped at 20,000 events per request
- Full historical archive via `starttime` and `endtime`

### NCEI Global Significant Earthquake Database

Documentation: https://www.ngdc.noaa.gov/hazel/view/swagger

- Only damaging events: a death, ~$1M damage, magnitude 7.5+, MMI X+, or a tsunami
- ~1,472 events in the same window
- Recorded deaths, injuries, damage in USD, houses destroyed and damaged
- Paginated JSON, 200 per page, no authentication

_Cite as: National Geophysical Data Center / World Data Service (NGDC/WDS): NCEI/WDS Global Significant Earthquake Database. NOAA National Centers for Environmental Information. doi:10.7289/V5TD9V7K_

### World Bank Indicators API

Documentation: https://datahelpdesk.worldbank.org/knowledgebase/articles/898581-api-basic-call-structures

- `SP.POP.TOTL`, total population per country per year
- Used to express deaths per million residents

## 🏗️ Architecture

Three DAGs, split by how often their sources actually change.

**`usgs_backfill`** — monthly, one pass over 26 years. Monthly rather than daily because a daily schedule over that span queues ~9,500 runs for no gain: the API returns a whole month in one request, well under the 20,000 cap.

**`usgs_pipeline`** — hourly. Waits for backfill, closes any ingestion gap, ingests, builds silver and gold, snapshots, then alerts.

**`reference_data`** — monthly. Regenerates the region seed, loads it, then refreshes World Bank population and NCEI records. Three things sharing a DAG because they share a rhythm, not a source.

Airflow, dbt, and the ingest scripts run in one container. Streamlit runs in its own. BigQuery and Telegram are external.

## 🥉🥈🥇 Data Model

**Bronze** — raw, append only, no transformation. `bronze_usgs_earthquake`, `bronze_ncei_earthquake`, `bronze_worldbank_population`.

**Silver** — cast, deduplicated, parsed. `silver_usgs_cleaned`, `silver_usgs_location`, `silver_usgs_category`, `silver_ncei_impact`, `silver_population`, plus the `seed_region_country` lookup.

**Gold** — a star schema for the event data, plus two tables that sit outside it.

- `gold_fact_earthquake` with seven dimensions, partitioned monthly on `event_date`, clustered on `location_id` and `magnitude_category_id`
- `gold_earthquake_impact`, one row per NCEI event with its matched `usgs_id`
- `gold_country_impact`, an aggregate at country-year grain
- `earthquake_snapshot`, SCD Type 2 revision history

Only the fact table is partitioned. The largest dimension is 187k rows and the rest are under 25, where partitioning adds metadata overhead without saving anything.

## 🔗 Reconciling Two Catalogs

USGS and NCEI share no identifier, so events are matched on time and distance. The thresholds were measured, not guessed. Against a deliberately loose window of 10 minutes and 200 km:

| Percentile | Time difference | Distance |
| ---------- | --------------- | -------- |
| Median     | 0 sec           | 0.0 km   |
| p90        | 0 sec           | 2.5 km   |
| p99        | 28 sec          | 15.2 km  |
| Max        | 558 sec         | 48.5 km  |

More than half the pairs are identical to the second and to the decimal, which suggests NCEI takes its event parameters from the same solutions USGS publishes.

**Final thresholds: 120 seconds and 50 km.** Well clear of the p99, tight enough to exclude coincidence. Where several USGS events fall inside the window, the closest is taken.

**Match rate: 94.3%.** The remaining 5.7% keep a null `usgs_id` rather than being dropped. Magnitude disagrees by more than 0.5 on 12 of 1,388 matches, under 1%, which is the cross-check that the pairing is real.

## ❓ Analytical Questions

1. Where do earthquakes happen the most?
2. Which regions feel the strongest earthquake impact?
3. How has the number of significant earthquakes changed each year?

Question 2 is measured by CDI, the community determined intensity from public reports, not by magnitude. A magnitude 7 far out at sea is felt by nobody; a 5.5 near a city can be felt strongly.

The dashboard also carries a section on recorded human cost and an open-ended heatmap for exploring the impact records.

## 🔍 Data Quality Findings

Every finding below was verified against the source, not assumed.

### The tsunami flag cannot be trusted before 2013

The 2004 Sumatra (M9.1), 2010 Chile Maule (M8.8), and 2011 Tōhoku (M9.1) earthquakes all return `tsunami: 0` from the live USGS API today, despite being among the deadliest tsunamis on record. Verified by calling the per-event endpoint directly.

**A planned analytical question was dropped because of this.** A replacement indicator was considered, built from magnitude, depth and an offshore proxy, but testing showed the proxy misclassified onland earthquakes: Denali Alaska 2002, Kahramanmaraş Turkey 2023, and Mandalay Myanmar 2025 all resolved as offshore because their place text broke the parser. The idea was abandoned rather than shipped.

### A 26-day ingestion gap, found only through cross-source reconciliation

`usgs_backfill` runs monthly and stopped at the end of July. `usgs_pipeline` started on 30 August with a two-day lookback. **Nothing covered 2 to 27 August.**

Every dbt test passed throughout, because tests check the rows that are there, not the ones that should be. The gap surfaced only when NCEI reported a magnitude 7.8 earthquake in Flores that killed 105 people, and no matching USGS event existed to pair it with.

Two fixes followed: the range was backfilled manually, and a custom test now fails when any day inside the loaded window holds zero events. USGS records around 14 earthquakes a day worldwide at this threshold, so a day with none is a day that was never ingested.

### USGS touches records without changing them

The snapshot started with `strategy='timestamp'`, trusting the `updated` field. Measured across the first 18 superseded rows it produced: magnitude changed 0 times, depth twice, felt reports five times, and **11 rows recorded no change at all**. USGS appears to bump `updated` every six hours as products like ShakeMap and DYFI regenerate.

Switched to `strategy='check'`, which compares the columns themselves.

### USGS has no country field

Only free text: `"95 km W of Petrolia, CA"`. Country and continent are derived through a seed built from `country_converter` and `pycountry`.

The place text comes in several shapes, and widening the parser recovered about **9,200 events** that had no country attribution:

- `"95 km W of Petrolia, CA"` — distance, direction, place, region
- `"Japan region"` — country name with a suffix
- `"2004 Sumatra - Andaman Islands Earthquake"` — historical title, no comma
- `"Southwest Indian Ridge"` — ocean, no country at all

### Three sources, three spellings

USGS writes "Turkey", "Micronesia", "Timor Leste". NCEI writes "USA", "UK", "MYANMAR (BURMA)". The reference libraries write "Türkiye", "Micronesia, Fed. Sts.", "Kyrgyz Republic". World Bank writes "Russian Federation" where the seed writes "Russia".

Resolved with an explicit alias list keyed on ISO3, so a rename upstream does not break the mapping. All joins between sources use ISO3, never a display name.

### Events with no country are left unmatched on purpose

About 15,000 USGS events sit on named ridges and seas — "Southwest Indian Ridge", "Banda Sea" — that belong to no country. In NCEI, 29 events resolve to nothing: the ambiguous "CONGO", which does not say whether it means DR Congo or Congo Republic, plus distant dependencies and open ocean.

Distant dependencies are excluded deliberately. South Sandwich Islands carries 5,210 events and is administered by the UK, but it is uninhabited. Attributing those events to the UK would divide them by 68 million residents and distort every per-capita figure.

### NCEI lags national agencies

For the August 2026 Flores earthquake, NCEI records 105 deaths where Indonesia's BNPB reports 129, three weeks after the event. Verified against the live API, so this is NCEI's own figure, not a stale copy.

Part of the difference is definitional: the reported 129 covers direct and indirect deaths. Part is lag: NCEI compiles from published reports while a national agency has field access.

The house damage figures looked four times apart until the columns were read properly. NCEI splits `housesDestroyed` (27,360) from `housesDamaged` (69,437); together that is 96,797 against BNPB's 98,986, a 2% difference.

### Coverage inside NCEI is uneven

| Field                     | Populated | Of 1,472 |
| ------------------------- | --------- | -------- |
| `country`                 | 1,472     | 100%     |
| Full timestamp            | 1,471     | 99.9%    |
| `injuries`                | 791       | 54%      |
| `deaths`                  | 598       | 41%      |
| `intensity`               | 574       | 39%      |
| `houses_destroyed`        | 411       | 28%      |
| `damage_millions_dollars` | 269       | 18%      |

Damage in dollars is too sparse to be a headline figure and is never summed as though it covered the whole set. Three events carry no magnitude at all, admitted to the catalog on the strength of their damage rather than a measured size.

### The Total variants include secondary effects

Of 598 events with a death count, 585 have `deaths` equal to `deathsTotal`, 13 differ, and 10 of those carry a tsunami event id. Another 13 have `deathsTotal` with no `deaths` at all. The pipeline uses the Total variants: for the 2004 Sumatra event, the tsunami deaths are the story.

### A metric that was built and then removed

An earlier version of the dashboard showed `events_per_million`: earthquake count divided by population. **The ratio measured nothing.** The numerator was geological events and the denominator was people; earthquakes do not happen to people proportionally.

The output made this obvious. Japan scored 7.96 against Indonesia's 4.36, despite Indonesia recording more earthquakes (1,246 vs 982) and having more than twice the population. The metric inverted the story it claimed to tell.

Replaced with `deaths_per_million`, where numerator and denominator are both people, which is how casualty rates are normally expressed.

### Small magnitudes are biased toward dense sensor networks

Below M2.5, almost all recorded events come from US regional networks — `ci`, `nc`, `ak`, `uu`, `hv` — not because small earthquakes only happen there, but because the instruments are denser. The M4.5 threshold is what makes the dataset globally comparable.

## ✅ Data Quality Testing

84 dbt tests: not-null, unique, relationships between the fact table and every dimension, accepted values on categorical columns, and range tests from `dbt_expectations` on magnitude, latitude and longitude. Source freshness is checked against `_ingested_at`.

Plus one custom test, `assert_no_ingestion_gaps`, written after the August gap. Generic tests validate the rows that exist; this one validates that no day is missing.

## ⚠️ Known Limitations

**NCEI covers only damaging earthquakes.** 1,472 events against 187,000 in USGS. It answers what earthquakes cost, never how often the ground moves.

**Country totals are a crude proxy for exposure.** Deaths per million uses national population, not population near an epicentre. A small country with one catastrophe tops the list on a single event — Samoa appears second on the strength of one earthquake.

**Damage in dollars covers 18% of events.** A country total is a floor, not an accounting.

**Ocean events have no country.** Filtering the dashboard to a country drops them, which understates island nations in particular.

**Impact estimates are not casualty predictions.** PAGER alert levels are USGS's own estimate of expected fatalities and economic loss, accurate to an order of magnitude. Predicting casualties properly needs population grids and building vulnerability curves, which is a different project.

## ⚙️ Setup

### Prerequisites

- Docker and Docker Compose
- A GCP project with BigQuery enabled
- A service account key with BigQuery Data Editor and Job User roles
- A Telegram bot token and chat id

### 1. Credentials

Place the service account JSON in `credentials/`. The path is mounted read-only into both containers.

Create `.env` in the project root:

```
# BigQuery
GCP_PROJECT_ID=your-project-id
BQ_BRONZE_DATASET=bronze
BQ_GOLD_DATASET=gold
BQ_OPS_DATASET=ops
BQ_LOCATION=asia-southeast2
GOOGLE_APPLICATION_CREDENTIALS=/opt/airflow/credentials/your-key.json

# USGS
USGS_MIN_MAGNITUDE=4.5

# Telegram
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
ALERT_MIN_MAGNITUDE=6.0
```

Two magnitude thresholds, and they are not the same thing. `USGS_MIN_MAGNITUDE` decides what enters the pipeline. `ALERT_MIN_MAGNITUDE` decides what reaches Telegram. Setting the second to 4.5 means every ingested event becomes an alert, roughly fourteen a day.

### 2. Create the BigQuery objects

Run `sql/setup_ddl.sql` in the BigQuery console. Set the query processing location to match `BQ_LOCATION` first, or the datasets will be created in the wrong region and every later query will fail on a cross-region join.

It creates four datasets and three tables: the two bronze tables and `ops.notification_log`. Silver and gold are dbt's responsibility.

### 3. Build and start

```bash
docker compose build
docker compose up -d
```

Four services come up: Postgres for Airflow metadata, the Airflow webserver and scheduler, and Streamlit. Airflow is at `localhost:8080` (admin/admin), Streamlit at `localhost:8501`.

### 4. Install dbt packages and load the seed

```bash
docker compose exec airflow-scheduler bash
cd /opt/airflow/dbt_project
dbt deps
```

Then generate and load the country lookup:

```bash
docker compose exec airflow-scheduler python3 /opt/airflow/scripts/generate_region_seed.py
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/dbt_project && dbt seed --full-refresh --select seed_region_country"
```

Watch the output of the first command. A line beginning `warning: alias` means an ISO3 in the alias list is no longer in the library data, and that alias needs revisiting.

### 5. Run the backfill, and wait

Unpause `usgs_backfill` in the Airflow UI. It walks 312 monthly windows from 2000 and stops on its own. This takes a while.

**Do not unpause `usgs_pipeline` until it finishes.** The pipeline builds incremental models, and if it runs against a half-loaded bronze, the historical rows that arrive later will never reach silver. The `wait_for_backfill` sensor guards against this, but the cheapest fix is to wait.

Check progress:

```sql
select min(_source_date) as earliest, max(_source_date) as latest, count(*) as rows
from `your-project.bronze.bronze_usgs_earthquake`
```

`earliest` should read 2000-01-01 when it is done.

### 6. Load the reference data

Trigger `reference_data` manually rather than waiting for the monthly schedule. Four tasks: regenerate the seed, load it, load World Bank population, load NCEI.

### 7. Start the pipeline

Unpause `usgs_pipeline`. First run takes longer than the rest, since silver and gold are built from scratch.

### 8. Snapshot

```bash
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/dbt_project && dbt snapshot"
```

Run once by hand to create the table. After that `usgs_pipeline` maintains it hourly.

---

## 🔧 Troubleshooting

### Editing files does nothing

`dags/`, `src/`, `scripts/`, `dbt_project/` and `app/` are mounted as volumes, so edits reach the container immediately. But Airflow re-parses DAGs on a timer and Streamlit's file watcher does not always see changes through a Docker mount, particularly on macOS.

```bash
docker compose restart airflow-scheduler streamlit
```

For changes to `.env` or `docker-compose.yml`, restart is not enough. Environment variables are read when the container is created:

```bash
docker compose up -d --force-recreate airflow-scheduler airflow-webserver streamlit
```

To confirm what the container actually sees:

```bash
docker compose exec airflow-scheduler python3 -c "
from telegram_notifier import ALERT_MIN_MAGNITUDE
print(ALERT_MIN_MAGNITUDE)
"
```

### A DAG will not load

```bash
docker compose exec airflow-scheduler airflow dags list-import-errors
```

Usually an import that does not resolve. Two common causes: a function referenced in a DAG that was never added to the module it imports from, and `PYTHONPATH` not covering the directory the module lives in.

### dbt cannot find a source

```
Compilation Error: depends on a source named 'bronze.x' which was not found
```

The table exists in BigQuery but is not declared in the sources YAML. dbt only knows what is declared. Add the entry under the existing `tables:` block.

### dbt commands fail with "No dbt_project.yml found"

You are in the wrong directory. Every dbt command runs from `/opt/airflow/dbt_project`:

```bash
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/dbt_project && dbt <command>"
```

### The dashboard shows nothing new

Check whether the problem is ingestion or the source:

```sql
select max(_ingested_at) as latest_ingest
from `your-project.bronze.bronze_usgs_earthquake`
```

If that is recent, the pipeline is alive. Then check whether anything actually happened:

```
https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=2026-09-04&minmagnitude=6
```

`"count":0` means the world was quiet, and silence is the correct output.

Streamlit also caches query results for five minutes, so a hard refresh may be needed.

### No Telegram alerts

Most often there is nothing to send. Magnitude 6 and above happens once or twice a week worldwide.

To see whether anything qualified and was already sent:

```sql
select fact.usgs_id, fact.event_time, fact.magnitude, fact.tsunami_flag,
       alert_lvl.alert_level, log.usgs_id is not null as already_notified
from `your-project.gold.gold_fact_earthquake` as fact
join `your-project.gold.gold_dim_alert_level` as alert_lvl using (alert_level_id)
left join `your-project.ops.notification_log` as log on fact.usgs_id = log.usgs_id
where fact.event_date >= date_sub(current_date(), interval 1 day)
  and (fact.magnitude >= 6.0 or fact.tsunami_flag = 1
       or alert_lvl.alert_level in ('orange', 'red'))
order by fact.event_time desc
```

A row with `already_notified` false is a real failure; check the `notify_telegram` task log.

To force one through for a demo, remove its log entry and run the notifier by hand:

```sql
delete from `your-project.ops.notification_log` where usgs_id = 'us7000te7l'
```

```bash
docker compose exec airflow-scheduler python3 -c "
from telegram_notifier import send_new_earthquake_alerts
send_new_earthquake_alerts()
"
```

### assert_no_ingestion_gaps fails

A day inside the loaded window has no events. Find which:

```sql
with bounds as (
  select min(event_date) as first_date, max(event_date) as last_date
  from `your-project.gold.gold_fact_earthquake`
),
calendar as (
  select day from bounds,
  unnest(generate_date_array(first_date, last_date)) as day
  where day > (select first_date from bounds)
    and day < (select last_date from bounds)
),
events_per_day as (
  select event_date, count(*) as events
  from `your-project.gold.gold_fact_earthquake` group by event_date
)
select calendar.day from calendar
left join events_per_day on calendar.day = events_per_day.event_date
where events_per_day.event_date is null
```

Backfill the range by hand. `endtime` is exclusive, so extend a day past the last gap:

```bash
docker compose exec airflow-scheduler python3 -c "
from load_to_bronze import load_range_to_bronze
load_range_to_bronze('2026-08-01', '2026-08-29')
"
```

Then rebuild. Silver and gold are incremental and will not pick up backdated rows without a full refresh:

```bash
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/dbt_project && dbt build --select silver gold --full-refresh"
```

Overlapping ranges are safe. Bronze is append only and silver keeps the newest copy per `usgs_id`.

### Country attribution looks wrong

Find the region names that resolved to nothing:

```sql
select region_raw, count(*) as events
from `your-project.silver.silver_usgs_location`
where country is null
group by region_raw
order by events desc
limit 30
```

For NCEI:

```sql
select ncei.country, count(*) as events
from `your-project.bronze.bronze_ncei_earthquake` as ncei
left join `your-project.silver.seed_region_country` as seed
  on lower(trim(ncei.country)) = lower(trim(seed.region))
where seed.region is null
group by ncei.country
order by events desc
```

Ocean names and distant dependencies belong in these lists; that is the design. A real country name appearing means a spelling the alias list does not cover. Add it to `SOURCE_ALIASES` in `scripts/generate_region_seed.py`, keyed on ISO3, then regenerate and reload the seed.

### Adding a column to an incremental model

`silver_usgs_cleaned` and `gold_fact_earthquake` are incremental. A new column will not appear on existing rows:

```bash
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/dbt_project && dbt build --select gold --full-refresh"
```

## 📚 References

U.S. Geological Survey. (2025, July 22). _Why are we having so many (or so few) earthquakes?_ https://www.usgs.gov/faqs/why-are-we-having-so-many-or-so-few-earthquakes-has-naturally-occurring-earthquake-activity

Bawono, A. S., Ramli, N. I., & Ali, M. I. (2026). Developing a tailored seismic risk assessment model for Indonesia: Insights from the Yogyakarta earthquake. _IOP Conference Series: Earth and Environmental Science_. https://iopscience.iop.org/article/10.1088/1755-1315/1605/1/012019

National Geophysical Data Center / World Data Service (NGDC/WDS). _NCEI/WDS Global Significant Earthquake Database_. NOAA National Centers for Environmental Information. doi:10.7289/V5TD9V7K
