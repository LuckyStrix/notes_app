from rq import Worker

from app.queue import job_queue, redis_conn

if __name__ == "__main__":
    worker = Worker([job_queue], connection=redis_conn)
    worker.work()
