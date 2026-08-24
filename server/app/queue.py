import redis
from rq import Queue, Retry

from app.config import settings

redis_conn = redis.from_url(settings.redis_url)
job_queue = Queue("default", connection=redis_conn)

# A couple of retries with backoff smooths over transient failures (Ollama
# briefly unreachable, a network blip) without masking persistent bugs --
# jobs that keep failing still end up in RQ's failed registry.
DEFAULT_RETRY = Retry(max=2, interval=[10, 30])
