"""Template terminal-status polling with caller-owned timeouts and evidence."""

import time
from .errors import ECWError

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "invalid"}


def poll_job(client, job_id, timeout_seconds, *, poll_interval=2, observe=None):
    deadline = time.monotonic() + timeout_seconds
    while True:
        job = client.request(f"/v1/ci/jobs/{job_id}")
        status = str(job.get("status", "")).lower()
        if observe is not None:
            observe(job)
        if status in TERMINAL_STATUSES:
            return job
        if time.monotonic() >= deadline:
            raise ECWError(f"Job {job_id} did not finish within {timeout_seconds} seconds")
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
