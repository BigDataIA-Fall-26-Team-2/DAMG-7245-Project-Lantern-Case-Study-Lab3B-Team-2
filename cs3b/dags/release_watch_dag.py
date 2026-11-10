"""Release watch (Airflow 3): is the next monthly SEC BDC release out?

Thin by design: the task calls a plain function in YOUR code, so pytest and the CLI can run the
same logic with an injected clock and recorded feeds. Write the other three DAGs the same way.
"""
import pendulum
from airflow.sdk import dag, task


@dag(dag_id="release_watch_dag",
     schedule="0 6 * * *",                       # daily, 06:00 New York time
     start_date=pendulum.datetime(2026, 10, 1, tz="America/New_York"),
     catchup=False, tags=["lantern", "cs3b"])
def release_watch():
    @task
    def tick():
        from services.heartbeat import release_job   # your code: all logic lives there
        return release_job()

    tick()


release_watch()
