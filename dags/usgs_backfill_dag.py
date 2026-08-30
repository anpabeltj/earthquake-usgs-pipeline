"""
Historical backfill of the USGS earthquake catalog, 2000 to present.

Runs once per logical month with catchup enabled, so Airflow walks
through roughly 312 monthly windows and stops on its own once it reaches
the present. Each run pulls about 580 events at magnitude 4.5 and above,
well inside the 20000 result cap on the API.

Monthly rather than daily on purpose. A daily schedule over 26 years
would queue around 9500 runs, which floods the scheduler and the UI for
no gain, since the API is happy to return a whole month at once.

Only bronze is loaded here. Transformations are left to the operational
DAG, because rebuilding silver and gold after every one of 312 windows
would repeat the same work hundreds of times over.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from load_to_bronze import load_range_to_bronze

default_args = {
    "owner": "data-engineering",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
}


def backfill_one_month(data_interval_start, data_interval_end, **context):
    """
    Load the month Airflow is currently working on.

    Taking the dates from the data interval rather than from the wall
    clock is what makes each run reproducible: re-running a window from
    2003 fetches 2003 again, not today.
    """
    start_date = data_interval_start.strftime("%Y-%m-%d")
    end_date = data_interval_end.strftime("%Y-%m-%d")

    return load_range_to_bronze(start_date, end_date)


with DAG(
    dag_id="usgs_backfill",
    description="One time historical load of the USGS catalog since 2000",
    default_args=default_args,
    start_date=datetime(2000, 1, 1),
    schedule="@monthly",
    catchup=True,
    # One month at a time. Without this, Airflow would fire dozens of
    # windows at the API simultaneously.
    max_active_runs=1,
    tags=["usgs", "backfill", "one-off"],
) as dag:

    load_month = PythonOperator(
        task_id="load_month_to_bronze",
        python_callable=backfill_one_month,
        doc_md="""
        Fetches one calendar month from the USGS catalog and appends it
        to bronze.

        Safe to clear and re-run. Bronze is append only, and silver keeps
        only the newest version of each event, so a repeated window adds
        rows without corrupting anything downstream.
        """,
    )