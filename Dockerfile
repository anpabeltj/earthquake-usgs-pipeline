# Two independent stages, picked with the "target" key in
# docker-compose.yml.

# ----------------------------------------------------------------
# Stage: airflow
# Runs the pipeline. dbt lives here rather than in its own container so
# Airflow can invoke it through a BashOperator.
# ----------------------------------------------------------------
FROM apache/airflow:2.10.5-python3.11 AS airflow

USER airflow

RUN pip install --no-cache-dir \
    dbt-core==1.8.7 \
    dbt-bigquery==1.8.3 \
    requests==2.32.3


# ----------------------------------------------------------------
# Stage: app
# Runs the Streamlit dashboard.
# ----------------------------------------------------------------
FROM python:3.11-slim AS app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
