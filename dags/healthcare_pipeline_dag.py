

from airflow.decorators import dag
from pendulum import datetime
from airflow.operators.bash import BashOperator
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
from cosmos.airflow.task_group import DbtTaskGroup
from dbt.healthcare_dbt_bigquery_data_pipeline.cosmos_config import DBT_PROJECT_CONFIG, DBT_CONFIG
from cosmos.constants import LoadMode
from cosmos.config import RenderConfig
from airflow.models import Variable

PATH_TO_DATA_SCRIPT = "/usr/local/airflow/include/raw_data_generation/healthcare_data.py"
PATH_TO_SQL_SCRIPT = "/usr/local/airflow/include/raw_data_generation/create_external_tables.sql"
GCP_CONN_ID = Variable.get("GCP_CONN_ID", default_var="gcp")
TARGET_ENV = DBT_CONFIG.target_name  # 'dev' or 'prod'

# Read and modify the SQL file dynamically based on env
with open(PATH_TO_SQL_SCRIPT, "r") as f:
    CREATE_EXTERNAL_TABLES_SQL = f.read() \
        .replace("dev_healthcare_data", f"{TARGET_ENV}_healthcare_data") \
        .replace("/dev/", f"/{TARGET_ENV}/")

@dag(
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["healthcare"],
    doc_md=__doc__,
)
def dbt_healthcare_pipeline():
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
        location="europe-west3",  # Matches BigQuery dataset location
        gcp_conn_id=GCP_CONN_ID,
    )

    if TARGET_ENV == "dev":
        dbt_test_raw = BashOperator(
            task_id="dbt_test_raw",
            bash_command="source /usr/local/airflow/dbt_venv/bin/activate && dbt test --select source:*",
            cwd="/usr/local/airflow/dbt/healthcare_dbt_bigquery_data_pipeline"
        )
        
        generate_data >> create_external_tables >> dbt_test_raw
    else:
        generate_data >> create_external_tables
    
    transform = DbtTaskGroup(
        group_id='transform',
        project_config=DBT_PROJECT_CONFIG,
        profile_config=DBT_CONFIG,  # Uses dynamic dbt profile from `cosmos_config.py`
        render_config=RenderConfig(
            load_method=LoadMode.DBT_LS,
            select=['path:models'],
            dbt_executable_path="source /usr/local/airflow/dbt_venv/bin/activate && /usr/local/airflow/dbt_venv/bin/dbt"
        )
        # operator_args={
        #         "install_deps": True
        #     }
    )
    
    if TARGET_ENV == "dev":
        dbt_test_raw >> transform
    else:
        create_external_tables >> transform

dbt_healthcare_pipeline()


