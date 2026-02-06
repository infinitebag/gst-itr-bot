# app/infrastructure/tasks/queue.py

from redis import Redis
from rq import Queue

from app.core.config import settings

redis_conn = Redis.from_url(settings.REDIS_URL)
default_queue = Queue("default", connection=redis_conn)
