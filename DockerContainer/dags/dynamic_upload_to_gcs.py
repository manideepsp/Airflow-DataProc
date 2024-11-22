import os
from airflow import DAG
from airflow.providers.google.cloud.transfers.local_to_gcs import LocalFilesystemToGCSOperator
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

# Default arguments for the DAG
default_args = {
    "owner": "airflow",
    "start_date": days_ago(1),
}

# Path inside the container where local files are mounted
LOCAL_PATH = "/opt/airflow/local-data"
GCS_BUCKET_NAME = "hospitaldata0101"  # Replace with your bucket name
GCS_FOLDER = "raw_data/"  # Folder inside the bucket

with DAG(
    dag_id="dynamic_upload_to_gcs",
    default_args=default_args,
    schedule_interval=None,
    catchup=False,
) as dag:

    # Step 1: List all files in the local directory
    list_files_task = PythonOperator(
        task_id="list_files",
        python_callable=lambda ti, **kwargs: ti.xcom_push(
            key='file_list', 
            value=[f for f in os.listdir(LOCAL_PATH) if os.path.isfile(os.path.join(LOCAL_PATH, f))]
        ),
        provide_context=True,
    )

    # Step 2: Dynamically create upload tasks for each file
    def upload_files(**kwargs):
        # Pulling the file list using XCom
        ti = kwargs['ti']
        file_list = ti.xcom_pull(task_ids='list_files', key='file_list')

        for file_name in file_list:
            # Sanitize the task_id by replacing spaces with underscores
            task_id = f"upload_{file_name.replace(' ', '_').replace('.', '_')}"
            
            # Dynamically create the task without pushing to XCom
            upload_files_task = LocalFilesystemToGCSOperator(
                task_id=task_id,
                src=os.path.join(LOCAL_PATH, file_name),
                dst=f"{GCS_FOLDER}{file_name}",  # Keeps the original file name in GCS
                bucket=GCS_BUCKET_NAME,  # Corrected parameter name to 'bucket'
            )

            # Execute the task immediately
            upload_files_task.execute(context=kwargs)

    # Create the upload tasks
    create_upload_tasks = PythonOperator(
        task_id='create_upload_tasks',
        python_callable=upload_files,
        provide_context=True,
    )

    # Step 3: Trigger the PySpark DAG after all upload tasks are completed
    trigger_pyspark_dag = TriggerDagRunOperator(
        task_id="trigger_pyspark_dag",
        trigger_dag_id="dataproc_pyspark_script_runner_bronze",  # Replace with the ID of your PySpark DAG
        wait_for_completion=False,  # Set to True if you want to wait for the triggered DAG to complete
    )

    # Set dependencies
    list_files_task >> create_upload_tasks >> trigger_pyspark_dag
