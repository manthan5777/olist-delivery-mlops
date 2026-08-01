import os
import time
from datetime import datetime, timezone

from redis import Redis


REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://redis:6379/0",
)

QUEUE_NAME = "olist:jobs"
JOB_KEY_PREFIX = "olist:job:"


redis_client = Redis.from_url(
    REDIS_URL,
    decode_responses=True,
)


print(
    f"Worker started. Waiting on {QUEUE_NAME}",
    flush=True,
)


while True:
    queued_item = redis_client.brpop(
        QUEUE_NAME,
        timeout=5,
    )

    if queued_item is None:
        continue

    _, job_id = queued_item
    job_key = f"{JOB_KEY_PREFIX}{job_id}"

    try:
        redis_client.hset(
            job_key,
            mapping={
                "status": "processing",
                "started_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
        )

        print(
            f"Processing job: {job_id}",
            flush=True,
        )

        # Simulates a long-running background task.
        time.sleep(3)

        redis_client.hset(
            job_key,
            mapping={
                "status": "completed",
                "result": "Demo background job completed",
                "completed_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
        )

        redis_client.expire(
            job_key,
            3600,
        )

        print(
            f"Completed job: {job_id}",
            flush=True,
        )

    except Exception as error:
        redis_client.hset(
            job_key,
            mapping={
                "status": "failed",
                "error": str(error),
            },
        )

        print(
            f"Job failed: {job_id}: {error}",
            flush=True,
        )
