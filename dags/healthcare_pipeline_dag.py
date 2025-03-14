import os
from airflow.decorators import dag
from pendulum import datetime
from airflow.operators.bash import BashOperator
from airflow.operators.python import BranchPythonOperator
from airflow.operators.dummy import DummyOperator
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
from airflow.models import Variable

# DAG configuration
PATH_TO_DATA_SCRIPT = "/usr/local/airflow/include/raw_data_generation/healthcare_data.py"
GCP_CONN_ID = Variable.get("GCP_CONN_ID", default_var="gcp")
# Read TARGET_ENV from Airflow Variable (set in Airflow UI)
TARGET_ENV = Variable.get("TARGET_ENV", default_var="dev")

# Dynamically construct the dataset name
DATASET = f"{TARGET_ENV}_healthcare_data"
PROJECT_ID = "healthcare-data-project-442109"

# Dynamically generate SQL based on TARGET_ENV
CREATE_EXTERNAL_TABLES_SQL = f"""
-- Creating patient_data external table (CSV format)
CREATE OR REPLACE EXTERNAL TABLE `{PROJECT_ID}.{DATASET}.patient_data_external`
OPTIONS (
  format = 'CSV',
  uris = ['gs://healthcare-data-bucket-emeka/prod/patient_data.csv', 'gs://healthcare-data-bucket-emeka/dev/patient_data.csv'],
  skip_leading_rows = 1
);

-- Creating ehr_data external table (JSON format)
CREATE OR REPLACE EXTERNAL TABLE `{PROJECT_ID}.{DATASET}.ehr_data_external`
OPTIONS (
  format = 'NEWLINE_DELIMITED_JSON',
  uris = ['gs://healthcare-data-bucket-emeka/prod/ehr_data.json', 'gs://healthcare-data-bucket-emeka/dev/ehr_data.json']
);

-- Creating claims_data external table (Parquet format with explicit schema)
CREATE OR REPLACE EXTERNAL TABLE `{PROJECT_ID}.{DATASET}.claims_data_external`
OPTIONS (
  format = 'PARQUET',
  uris = ['gs://healthcare-data-bucket-emeka/prod/claims_data.parquet', 'gs://healthcare-data-bucket-emeka/dev/claims_data.parquet']
);
"""

@dag(
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["healthcare"],
    doc_md=__doc__,
)
def dbt_healthcare_pipeline():
    # Branch function to decide whether to run dbt_test_raw
    def branch_func():
        if TARGET_ENV == "prod":
            return "skip_dbt_test_raw"  # Skip dbt_test_raw in prod
        return "dbt_test_raw"  # Run dbt_test_raw in non-prod

    generate_data = BashOperator(
        task_id="generate_data",
        bash_command=f"python {PATH_TO_DATA_SCRIPT}"
    )

    create_external_tables = BigQueryInsertJobOperator(
        task_id="create_external_tables",
        configuration={
            "query": {
                "query": CREATE_EXTERNAL_TABLES_SQL,
                "useLegacySql": False,
            }
        },
        location="europe-west3",
        gcp_conn_id=GCP_CONN_ID
    )

    # Branch to decide whether to run dbt_test_raw
    branch_task = BranchPythonOperator(
        task_id="branch_dbt_test_raw",
        python_callable=branch_func
    )

    dbt_test_raw = BashOperator(
        task_id="dbt_test_raw",
        bash_command=f"dbt test --select source:* --target {TARGET_ENV}",
        cwd="/usr/local/airflow/dbt/healthcare_dbt_bigquery_data_pipeline",
    )

    # Dummy task to skip dbt_test_raw
    skip_dbt_test_raw = DummyOperator(
        task_id="skip_dbt_test_raw"
    )

    transform = BashOperator(
        task_id="transform",
        bash_command=f"dbt deps && dbt run --select path:models --target {TARGET_ENV}",
        cwd="/usr/local/airflow/dbt/healthcare_dbt_bigquery_data_pipeline",
        trigger_rule="all_done"  # Run regardless of upstream task status
    )

    # Define the DAG structure
    generate_data >> create_external_tables >> branch_task
    branch_task >> [dbt_test_raw, skip_dbt_test_raw]
    dbt_test_raw >> transform
    skip_dbt_test_raw >> transform

dbt_healthcare_pipeline()