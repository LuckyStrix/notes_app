import threading

from rq import Worker

from app.jobs.backup import scheduler_loop
from app.queue import job_queue, redis_conn

if __name__ == "__main__":
    threading.Thread(target=scheduler_loop, name="backup-scheduler", daemon=True).start()
    worker = Worker([job_queue], connection=redis_conn)
    worker.work()
