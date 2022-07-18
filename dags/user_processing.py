import json

import pandas as pd
import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.http.operators.http import SimpleHttpOperator
from airflow.providers.http.sensors.http import HttpSensor
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.postgres.operators.postgres import PostgresOperator


def _process_user(ti):
    user = ti.xcom_pull(task_ids="extract_user")
    user = user["results"][0]
    processed_user = pd.json_normalize(
        {
            "firstname": user["name"]["first"],
            "lastname": user["name"]["last"],
            "country": user["location"]["country"],
            "username": user["login"]["username"],
            "password": user["login"]["password"],
            "email": user["email"],
        }
    )
    processed_user.to_csv("/tmp/processed_user.csv", index=False, header=False)


def _store_user(ti):
    hook = PostgresHook(postgres_conn_id="postgres")
    hook.copy_expert(
        sql="COPY users FROM stdin WITH DELIMITER as ','",
        filename="/tmp/processed_user.csv",
    )


with DAG(
    dag_id="user_processing",
    schedule_interval="@daily",
    start_date=pendulum.datetime(year=2021, month=1, day=1),
    catchup=False,
) as dag:

    create_table = PostgresOperator(
        task_id="create_table",
        postgres_conn_id="postgres",
        sql="""
            CREATE TABLE IF NOT EXISTS users (
                firstname TEXT NOT NULL,
                lastname TEXT NOT NULL,
                country TEXT NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                email TEXT NOT NULL
            );
            """,
    )

    is_api_available = HttpSensor(
        task_id="is_api_available", http_conn_id="user_api", endpoint="/api"
    )

    extract_user = SimpleHttpOperator(
        task_id="extract_user",
        http_conn_id="user_api",
        method="GET",
        endpoint="/api",
        response_filter=lambda response: json.loads(response.text),
        log_response=True,
    )

    process_user = PythonOperator(
        task_id="process_user",
        python_callable=_process_user,
    )

    store_user = PythonOperator(task_id="store_user", python_callable=_store_user)

    create_table >> is_api_available >> extract_user >> process_user >> store_user
