"""Template artifact download, parameterized destination and job ID."""


def download_artifact(client, job_id, destination):
    client.download(f"/v1/ci/jobs/{job_id}/artifacts.zip", destination)
    return destination
