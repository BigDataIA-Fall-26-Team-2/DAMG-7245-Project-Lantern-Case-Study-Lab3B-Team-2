"""Airflow 3 wrapper; plain workflow functions are also executable offline."""
import pendulum
from airflow.sdk import dag, task


@dag(dag_id="release_watch_dag", schedule="0 6 * * *",
     start_date=pendulum.datetime(2026, 10, 1, tz="America/New_York"),
     catchup=False, max_active_runs=1, default_args={"retries": 2}, tags=["lantern", "cs3b"])
def release_watch():
    @task
    def run_workflow():
        from airflow.sdk import get_current_context
        from services.heartbeat import release_job
        # Use the scheduled interval end, not the fixed notebook clock.
        context = get_current_context()
        return release_job(now=context["data_interval_end"])
    run_workflow()


release_watch_dag = release_watch()
