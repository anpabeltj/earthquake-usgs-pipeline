# 🌍 USGS Global Earthquake Data Pipeline

An end-to-end data pipeline that ingests earthquake events from the USGS global earthquake catalog, transforms them through a Bronze, Silver, Gold architecture, and serves the results through an interactive Streamlit dashboard with automated Telegram alerts for significant events.

## 🛠️ Tech Stack

- **Orchestration**: Apache Airflow (running in Docker) 🐳
- **Transformation**: dbt 🔧
- **Warehouse**: Google BigQuery 🗄️
- **Dashboard**: Streamlit 📊
- **Alerting**: Telegram Bot API 🔔
- **Language**: Python, SQL 🐍

## 📡 Data Source

[USGS Earthquake Catalog API](https://earthquake.usgs.gov/fdsnws/event/1/), an implementation of the FDSN Event Web Service Specification.

- Endpoint: `https://earthquake.usgs.gov/fdsnws/event/1/query`
- Format: GeoJSON
- Filter: magnitude ≥ 4.5
- Coverage: global, backfilled from 2000 to present
- No authentication required

## 🏗️ Architecture

1. **Ingest** 📥 — Airflow triggers `extract_usgs.py`, which pulls events from the USGS API and hands them to `load_to_bronze.py`, which writes them into BigQuery Bronze. Schema is created by `setup_ddl.sql`.
2. **Transform (Silver)** 🥈 — dbt staging models clean and standardize Bronze into Silver. `generate_region_seed.py` adds region and country lookups derived from latitude/longitude.
3. **Transform (Gold)** 🥇 — dbt mart models aggregate Silver into Gold, the tables the dashboard reads from.
4. **Serve** 🖥️ — Streamlit reads Gold directly and renders the dashboard.
5. **Notify** 📲 — `telegram_notifier.py` checks new Gold records against a configured magnitude threshold and sends Telegram alerts for significant events, avoiding duplicate alerts for the same event.

Airflow, dbt, the scripts above, and Streamlit all run inside Docker. BigQuery and Telegram are external managed services the pipeline connects to over the network.

## 🥉 Bronze Schema — `bronze_usgs_earthquake`

| Column           | Type      | Description                       |
| ---------------- | --------- | --------------------------------- |
| `usgs_id`        | STRING    | Unique event id                   |
| `magnitude`      | FLOAT64   | Preferred magnitude               |
| `place`          | STRING    | Free text location description    |
| `event_time_ms`  | INT64     | Event time, epoch ms UTC          |
| `updated_ms`     | INT64     | Last revision time, epoch ms UTC  |
| `felt_reports`   | INT64     | Number of Did You Feel It reports |
| `cdi`            | FLOAT64   | Max reported intensity            |
| `mmi`            | FLOAT64   | Max instrumental intensity        |
| `alert`          | STRING    | PAGER alert level                 |
| `status`         | STRING    | automatic / reviewed              |
| `tsunami_flag`   | INT64     | Tsunami relevance flag            |
| `significance`   | INT64     | Significance score                |
| `network`        | STRING    | Reporting network code            |
| `station_count`  | INT64     | Stations used                     |
| `azimuthal_gap`  | FLOAT64   | Azimuthal gap, degrees            |
| `rms`            | FLOAT64   | RMS travel time residual          |
| `magnitude_type` | STRING    | Magnitude method                  |
| `event_type`     | STRING    | Event type                        |
| `longitude`      | FLOAT64   | Epicentre longitude               |
| `latitude`       | FLOAT64   | Epicentre latitude                |
| `depth_km`       | FLOAT64   | Hypocentre depth                  |
| `_ingested_at`   | TIMESTAMP | Pipeline write time               |
| `_source_date`   | DATE      | Partition key                     |

## 🥈 Silver Layer

### `silver_usgs_cleaned`

| Column           | Key | Description                           |
| ---------------- | --- | ------------------------------------- |
| `usgs_id`        | PK  | Unique event id                       |
| `event_time`     |     | Event time                            |
| `updated_at`     |     | Last revision time                    |
| `magnitude`      |     | Event magnitude                       |
| `magnitude_type` |     | Magnitude measurement method          |
| `depth_km`       |     | Hypocentre depth                      |
| `latitude`       |     | Epicentre latitude                    |
| `longitude`      |     | Epicentre longitude                   |
| `felt_reports`   |     | Number of Did You Feel It reports     |
| `cdi`            |     | Max reported intensity                |
| `mmi`            |     | Max instrumental intensity            |
| `alert`          |     | PAGER alert level                     |
| `tsunami_flag`   |     | Tsunami relevance flag                |
| `significance`   |     | Significance score                    |
| `station_count`  |     | Stations used                         |
| `azimuthal_gap`  |     | Azimuthal gap, degrees                |
| `network`        |     | Reporting network code                |
| `status`         |     | automatic / reviewed                  |
| `raw_place`      |     | Original free text location from USGS |

### `silver_usgs_category`

| Column               | Key                      | Description        |
| -------------------- | ------------------------ | ------------------ |
| `usgs_id`            | FK → silver_usgs_cleaned | Event id           |
| `magnitude_category` |                          | Magnitude bucket   |
| `depth_category`     |                          | Depth bucket       |
| `alert_level`        |                          | Alert level bucket |

### `silver_usgs_location`

| Column          | Key                      | Description                            |
| --------------- | ------------------------ | -------------------------------------- |
| `usgs_id`       | FK → silver_usgs_cleaned | Event id                               |
| `direction`     |                          | Direction from nearest reference place |
| `distance_km`   |                          | Distance from nearest reference place  |
| `nearest_place` |                          | Nearest named place                    |
| `region_raw`    |                          | Raw region string                      |
| `country`       |                          | Country, derived from coordinates      |
| `continent`     |                          | Continent, derived from coordinates    |

## 🥇 Gold Layer

### `gold_fact_earthquake`

| Column                  | Key                              | Description                       |
| ----------------------- | -------------------------------- | --------------------------------- |
| `usgs_id`               | PK                               | Unique event id                   |
| `time_id`               | FK → gold_dim_time               |                                   |
| `location_id`           | FK → gold_dim_location           |                                   |
| `magnitude_category_id` | FK → gold_dim_magnitude_category |                                   |
| `depth_category_id`     | FK → gold_dim_depth_category     |                                   |
| `magnitude_type_id`     | FK → gold_dim_magnitude_type     |                                   |
| `alert_level_id`        | FK → gold_dim_alert_level        |                                   |
| `network_id`            | FK → gold_dim_network            |                                   |
| `magnitude`             |                                  | Event magnitude                   |
| `depth_km`              |                                  | Hypocentre depth                  |
| `felt_reports`          |                                  | Number of Did You Feel It reports |
| `cdi`                   |                                  | Max reported intensity            |
| `mmi`                   |                                  | Max instrumental intensity        |
| `significance`          |                                  | Significance score                |
| `station_count`         |                                  | Stations used                     |
| `azimuthal_gap`         |                                  | Azimuthal gap, degrees            |
| `tsunami_flag`          |                                  | Tsunami relevance flag            |
| `latitude`              |                                  | Epicentre latitude                |
| `longitude`             |                                  | Epicentre longitude               |
| `loaded_at`             |                                  | Gold load timestamp               |
| `event_date`            |                                  | Event date                        |

**Partitioning**: `event_date`, monthly · **Clustering**: `location_id`, `magnitude_category_id`

### Dimension tables

| Table                         | PK                      | Columns                                   |
| ----------------------------- | ----------------------- | ----------------------------------------- |
| `gold_dim_location`           | `location_id`           | nearest_place, region, country, continent |
| `gold_dim_time`               | `time_id`               | date, hour, day_name, month, year         |
| `gold_dim_magnitude_category` | `magnitude_category_id` | magnitude_category                        |
| `gold_dim_magnitude_type`     | `magnitude_type_id`     | magnitude_type                            |
| `gold_dim_depth_category`     | `depth_category_id`     | depth_category                            |
| `gold_dim_alert_level`        | `alert_level_id`        | alert_level                               |
| `gold_dim_network`            | `network_id`            | network                                   |

## ❓ Analytical Questions

1. 🗺️ Where do earthquakes happen the most?
2. 📈 Which regions feel the strongest earthquake impact?
3. 🌊 How many earthquakes each year are flagged with tsunami potential?

## 📂 Project Structure

> Example layout, adjust to match your actual repo.

```
.
├── dags/
│   ├── usgs_backfill_dag.py
│   └── usgs_pipeline_dag.py
├── scripts/
│   ├── extract_usgs.py
│   ├── load_to_bronze.py
│   ├── generate_region_seed.py
│   └── telegram_notifier.py
├── sql/
│   └── setup_ddl.sql
├── dbt/
│   ├── models/
│   │   ├── staging/
│   │   └── marts/
│   └── dbt_project.yml
├── streamlit_app/
│   └── app.py
├── docker-compose.yml
└── README.md
```

## ⚙️ Setup

<!-- TODO: fill in with your actual steps, e.g. -->
<!-- 1. Set environment variables (GCP service account, Telegram bot token, BigQuery project id) -->
<!-- 2. docker-compose up -->
<!-- 3. dbt deps && dbt run -->
<!-- 4. streamlit run streamlit_app/app.py -->

## ✅ Success Metrics

- **Data completeness** 📦: at least 95% of events returned by the USGS API for a given run window are ingested into Bronze
- **Data quality** 🔍: transformed fields pass dbt tests (not-null, accepted values, relationships) with at least 95% pass rate
- **Pipeline reliability** 🔁: the Airflow DAG completes successfully at least 95% of the time over a one-week monitoring period
- **Alerting reliability** 🔔: no duplicate Telegram alerts for the same event
- **Dashboard usability** 🎯: the dashboard can answer all three analytical questions above

## 📚 References

- U.S. Geological Survey. (2025, July 22). _Why are we having so many (or so few) earthquakes? Has naturally occurring earthquake activity been increasing?_ https://www.usgs.gov/faqs/why-are-we-having-so-many-or-so-few-earthquakes-has-naturally-occurring-earthquake-activity
- Bawono, A. S., Ramli, N. I., & Ali, M. I. (2026). Developing a tailored seismic risk assessment model for Indonesia: Insights from the Yogyakarta earthquake. _IOP Conference Series: Earth and Environmental Science_. https://iopscience.iop.org/article/10.1088/1755-1315/1605/1/012019
