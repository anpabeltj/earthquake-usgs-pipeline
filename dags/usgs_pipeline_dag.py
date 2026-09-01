"""
Operational pipeline for the USGS earthquake catalog.

Runs hourly and covers the whole flow:

    ingest -> silver -> gold -> notify

The ingest window looks back two days rather than one hour. USGS revises
events after review, sometimes hours later, and a wider window picks up
those corrections instead of leaving the first automatic estimate in
place forever.

This DAG assumes the historical backfill has already been run. It only
keeps the recent end of the catalog current.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from load_to_bronze import load_range_to_bronze
from telegram_notifier import send_new_earthquake_alerts

DBT_PROJECT_DIR = "/opt/airflow/dbt_project"

LOOKBACK_DAYS = 2

default_args = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "depends_on_past": False,
}


def load_recent_events(data_interval_end, **context):
    """Load the last couple of days, so revisions are picked up too."""
    end_date = (data_interval_end + timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (data_interval_end - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    return load_range_to_bronze(start_date, end_date)


with DAG(
    dag_id="usgs_pipeline",
    description="Hourly ingest, transform, and alert for USGS earthquakes",
    default_args=default_args,
    start_date=datetime(2026, 8, 1),
    schedule="@hourly",
    catchup=False,
    max_active_runs=1,
    tags=["usgs", "medallion"],
) as dag:

    ingest_to_bronze = PythonOperator(
        task_id="ingest_to_bronze",
        python_callable=load_recent_events,
        doc_md="""
        Pulls the last two days from the USGS catalog into bronze.

        Overlapping windows are intentional. Repeated events cost almost
        nothing and revised ones replace their earlier version in silver.
        """,
    )

    build_silver = BashOperator(
        task_id="build_silver",
        bash_command=f"cd {DBT_PROJECT_DIR} && dbt build --select silver --target dev",
        doc_md="""
        Deduplicates by usgs_id keeping the newest revision, casts the
        epoch timestamps, and parses the free text place field.
        """,
    )

    build_gold = BashOperator(
        task_id="build_gold",
        bash_command=f"cd {DBT_PROJECT_DIR} && dbt build --select gold --target dev",
        doc_md="""
        Rebuilds the star schema the dashboard and the alerts read from.

        The fact table is incremental, so this merges the recent window
        rather than rewriting all 180 thousand rows every hour.
        """,
    )

    notify_telegram = PythonOperator(
        task_id="notify_telegram",
        python_callable=send_new_earthquake_alerts,
        doc_md="""
        Announces events above magnitude 6, flagged for tsunami, or
        carrying an orange or red PAGER alert.

        Runs last because it reads gold. Everything it sends is written
        to the notification log, so a retry sends nothing twice.
        """,
    )

    ingest_to_bronze >> build_silver >> build_gold >> notify_telegram
