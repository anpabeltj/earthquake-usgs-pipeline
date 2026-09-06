"""
Monthly refresh of the slow moving sources.

Three things share this DAG because they share a rhythm, not because
they share a source. None of them changes hourly:

  The region seed only changes when country_converter or pycountry are
  updated, or when a new spelling is added to the alias list.

  World Bank population is published once a year and revised
  occasionally as censuses land.

  NCEI significant earthquakes are revised as death tolls and damage
  figures come in from the field, over weeks and months rather than
  hours.

Refetching any of them hourly would append thousands of unchanged rows
for no gain. Monthly is already more often than any of them changes.

Only bronze and the seed are handled here. silver and gold are rebuilt
by usgs_pipeline, which already runs those selectors every hour.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from load_ncei_to_bronze import load_ncei_to_bronze
from load_population_to_bronze import load_population_to_bronze

SCRIPTS_DIR = "/opt/airflow/scripts"
DBT_PROJECT_DIR = "/opt/airflow/dbt_project"

default_args = {
    "owner": "data-engineering",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
}


with DAG(
    dag_id="reference_data",
    description="Monthly refresh of the region seed, World Bank population, and NCEI impact records",
    default_args=default_args,
    start_date=datetime(2026, 8, 1),
    schedule="@monthly",
    catchup=False,
    max_active_runs=1,
    tags=["reference-data", "worldbank", "ncei"],
) as dag:

    regenerate_region_seed = BashOperator(
        task_id="regenerate_region_seed",
        bash_command=f"python3 {SCRIPTS_DIR}/generate_region_seed.py",
        doc_md="""
        Rewrites seeds/seed_region_country.csv from country_converter
        and pycountry, plus the alias list for spellings neither
        library produces.

        Both earthquake sources need it, for different reasons. USGS
        has no country field at all, only free text. NCEI has one but
        writes it in its own style: "USA", "UK", "MYANMAR (BURMA)".

        Note that a rename upstream, Turkey becoming Türkiye for
        instance, silently stops matching until someone notices, which
        is worth checking after this task changes the file.
        """,
    )

    load_region_seed = BashOperator(
        task_id="load_region_seed",
        bash_command=f"cd {DBT_PROJECT_DIR} && dbt seed --select seed_region_country --target dev",
        doc_md="""
        Loads the regenerated CSV into BigQuery. dbt seed is a full
        replace, so the table always matches the file.
        """,
    )

    load_population = PythonOperator(
        task_id="load_population_to_bronze",
        python_callable=load_population_to_bronze,
        doc_md="""
        Fetches the whole SP.POP.TOTL series from 2000 onward and
        appends it to bronze.

        No date window. The series is a few thousand rows and the World
        Bank revises past years, so refetching everything is both cheap
        and the only way to pick those revisions up.
        """,
    )

    load_ncei = PythonOperator(
        task_id="load_ncei_to_bronze",
        python_callable=load_ncei_to_bronze,
        doc_md="""
        Fetches every NCEI significant earthquake from 2000 onward,
        eight pages of 200, and appends them to bronze.

        Same reasoning as population: the whole set is under two
        thousand rows, the API gives no way to ask what changed, and
        NCEI revises death tolls long after an event. Silver keeps the
        most recently ingested copy of each event.
        """,
    )

    regenerate_region_seed >> load_region_seed >> load_population >> load_ncei