"""Template job loading/submission; return IDs instead of writing provider files."""

import json
from pathlib import Path
from .errors import ECWError


def _label(job_file: Path) -> str:
    stem = job_file.stem
    prefix, _, rest = stem.partition("_")
    return rest if prefix.isdigit() and rest else stem


def _loadJobSpecs(jobs_dir: Path) -> dict[str, dict]:
    job_files = sorted(jobs_dir.glob("*.json"))
    if not job_files:
        raise ValueError(f"No CI job specs found under {jobs_dir}.")
    specs = {}
    for job_file in job_files:
        if job_file.stat().st_size > 256 * 1024:
            raise ValueError(f"Job file is too large: {job_file}")
        label = _label(job_file)
        if label in specs:
            raise ValueError(f"Duplicate job label: {label}")
        specs[label] = json.loads(job_file.read_text(encoding="utf-8"))
    return specs


def create_job(client, booking_id, spec):
    payload = {**spec, "booking_id": booking_id}
    job = client.request("/v1/ci/jobs", method="POST", body=payload, timeout=30)
    job_id = job.get("id")
    if type(job_id) is not int or job_id <= 0:
        raise ECWError("Job creation response is missing a positive integer id")
    return job
