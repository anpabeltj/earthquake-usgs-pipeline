"""
Operational pipeline for the USGS earthquake catalog.

Runs hourly and covers the whole flow:

    wait for backfill -> close gap -> ingest -> silver -> gold
    -> snapshot -> notify

The ingest window looks back two days rather than one hour. USGS revises
events after review, sometimes hours later, and a wider window picks up
those corrections instead of leaving the first automatic estimate in
place forever.

The region seed is not loaded here. It is owned by the
worldbank_population DAG, which regenerates the CSV and seeds it
monthly, since its contents only change when country_converter or
pycountry are updated.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

from load_to_bronze import (
    backfill_has_reached_start,
    close_ingestion_gap,
    load_range_to_bronze,
)
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

    wait_for_backfill = PythonSensor(
        task_id="wait_for_backfill",
        python_callable=backfill_has_reached_start,
        poke_interval=300,
        timeout=60 * 60 * 6,
        mode="reschedule",
        doc_md="""
        Waits until bronze holds data back to 2000-01-01 before the
        first real ingest runs. usgs_backfill works through 26 years on
        its own monthly schedule, and this DAG must not build silver or
        gold from a half loaded bronze.

        Checks bronze directly rather than sensing a backfill DagRun,
        since the two DAGs have no comparable execution date. Passes
        immediately once backfill has caught up, and stays a cheap
        no-op on every run after that. mode=reschedule releases the
        worker slot between checks instead of holding it while waiting.
        """,
    )

    close_gap = PythonOperator(
        task_id="close_ingestion_gap",
        python_callable=close_ingestion_gap,
        doc_md="""
        Checks the latest _source_date already in bronze against today.
        If there is a gap, because this DAG was paused or because
        backfill finished on an earlier day than this DAG was enabled,
        fetches the missing days in chunks before the normal hourly
        ingest runs. No-op when there is no gap.
        """,
    )

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

    snapshot_earthquakes = BashOperator(
        task_id="snapshot_earthquakes",
        bash_command=f"cd {DBT_PROJECT_DIR} && dbt snapshot --target dev",
        doc_md="""
        Records the current version of every changed event into
        earthquake_snapshot, keeping full revision history as SCD type
        2. Runs after silver is rebuilt, since the snapshot reads from
        silver_usgs_cleaned.
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

    (
        wait_for_backfill
        >> close_gap
        >> ingest_to_bronze
        >> build_silver
        >> build_gold
        >> snapshot_earthquakes
        >> notify_telegram
    )