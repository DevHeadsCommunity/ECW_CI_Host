"""Validate project jobs, run them sequentially, and verify collected evidence."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import zipfile

from .client import ECWError
from .create_jobs import _loadJobSpecs, create_job
from .poll_jobs import TERMINAL_STATUSES, poll_job
from .download_artifacts import download_artifact

TERMINAL = TERMINAL_STATUSES
TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


@dataclass(frozen=True)
class JobSpec:
    label: str
    payload: dict
    checks: list


def load_specs(directory: Path) -> list[JobSpec]:
    specs = []
    labels = set()
    for label, spec in _loadJobSpecs(directory).items():
        path = Path(directory) / f"{label}.json"
        if not isinstance(spec, dict):
            raise ValueError(f"Job must be an object: {path}")
        json.dumps(spec, allow_nan=False)
        if "booking_id" in spec:
            raise ValueError("Job files cannot override the booking selected by the runner")
        unknown = set(spec) - {"request_id", "name", "description", "duration_seconds", "commands", "metadata", "checks"}
        if unknown:
            raise ValueError(f"Unknown fields in {path.name}: {sorted(unknown)}")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", label) or label in labels:
            raise ValueError("Job labels must be unique safe filenames of at most 40 characters")
        labels.add(label)
        duration = spec.get("duration_seconds")
        commands = spec.get("commands")
        if type(duration) is not int or not 0 < duration <= 86400:
            raise ValueError(f"{label}: duration_seconds must be a positive integer <= 86400")
        if not isinstance(commands, list) or not 1 <= len(commands) <= 50:
            raise ValueError(f"{label}: provide between 1 and 50 commands")
        identifiers, budget = set(), 0
        for command in commands:
            if not isinstance(command, dict):
                raise ValueError(f"{label}: every command must be an object")
            identifier = command.get("id", "")
            if not isinstance(identifier, str) or not TOKEN.fullmatch(identifier) or identifier in identifiers:
                raise ValueError(f"{label}: command ids must be unique safe tokens")
            identifiers.add(identifier)
            if not isinstance(command.get("command"), str) or not command["command"]:
                raise ValueError(f"{label}: commands need a public ECW command name")
            if command["command"] == "twister.run":
                raise ValueError("Twister owns its build and flash; this first-version MCU upload workflow cannot run twister.run")
            attempts, timeout = command.get("attempts", 1), command.get("timeout_ms", 0)
            if type(attempts) is not int or attempts < 1 or type(timeout) is not int or timeout < 0:
                raise ValueError(f"{label}: invalid command attempts or timeout")
            if "parameters" in command and not isinstance(command["parameters"], dict):
                raise ValueError(f"{label}: command parameters must be an object")
            budget += attempts * timeout
        if budget > duration * 1000:
            raise ValueError(f"{label}: command budgets exceed duration_seconds")
        checks = spec.pop("checks", [])
        if not isinstance(checks, list):
            raise ValueError(f"{label}: checks must be an array")
        for check in checks:
            if not isinstance(check, dict) or check.get("type") not in {"text_contains", "serial_sequence", "jpeg"}:
                raise ValueError(f"{label}: unknown evidence check")
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", check.get("file", "")):
                raise ValueError(f"{label}: checks must identify a single safe artifact basename")
            if check["type"] == "text_contains" and not isinstance(check.get("text"), str):
                raise ValueError("text_contains requires text")
            if check["type"] == "serial_sequence":
                pattern = re.compile(check.get("pattern", ""))
                if "sample" not in pattern.groupindex:
                    raise ValueError("serial_sequence pattern needs a named (?P<sample>...) group")
                if type(check.get("minimum", 4)) is not int or check.get("minimum", 4) < 2:
                    raise ValueError("serial_sequence minimum must be an integer >= 2")
        if "metadata" in spec and (not isinstance(spec["metadata"], dict)
                                     or len(json.dumps(spec["metadata"], allow_nan=False).encode()) > 2048):
            raise ValueError("Job metadata must be an object of at most 2048 bytes")
        spec.setdefault("name", label)
        if not isinstance(spec["name"], str) or not 1 <= len(spec["name"]) <= 120:
            raise ValueError("Job name must contain 1 to 120 characters")
        specs.append(JobSpec(label, spec, checks))
    if not specs:
        raise ValueError(f"No JSON jobs found in {directory}")
    return specs


def read_member(bundle: Path, basename: str) -> bytes:
    # Never extract server-provided ZIP paths onto the filesystem.
    with zipfile.ZipFile(bundle) as archive:
        matches = [item for item in archive.infolist() if Path(item.filename).name == basename]
        if len(matches) != 1 or matches[0].is_dir() or matches[0].file_size > 4 * 1024 * 1024:
            raise ECWError(f"Missing, duplicate, or oversized evidence member: {basename}")
        return archive.read(matches[0])


def verify_checks(bundle: Path, checks: list) -> list:
    verified = []
    for check in checks:
        data = read_member(bundle, check["file"])
        result = {"type": check["type"], "file": check["file"]}
        if check["type"] == "jpeg":
            if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
                raise ECWError("Camera artifact lacks JPEG start/end markers")
        else:
            text = data.decode("utf-8", errors="replace")
            if check["type"] == "text_contains" and check["text"] not in text:
                raise ECWError(f"Required text is absent from {check['file']}")
            if check["type"] == "serial_sequence":
                values = [int(match.group("sample")) for match in re.finditer(check["pattern"], text)]
                if len(values) < check.get("minimum", 4) or any(b != a + 1 for a, b in zip(values, values[1:])):
                    raise ECWError("Serial evidence does not contain enough consecutive firmware samples")
                result.update(samples=len(values), first=values[0], last=values[-1])
        verified.append({**result, "passed": True})
    return verified


def _collect(client, root, prefix, evidence):
    errors = []
    results = None
    for endpoint in ("results", "logs", "artifacts.zip"):
        try:
            if endpoint.endswith(".zip"):
                download_artifact(client, int(root.rsplit("/", 1)[1]), evidence.root / prefix / endpoint)
            elif endpoint == "results":
                results = client.request(root + "/results")
                evidence.write(prefix + "/results.json", results)
            else:
                logs, cursor = [], 0
                for _ in range(64):
                    page = client.request(root + "/logs", params={"cursor": cursor})
                    rows = page.get("logs", [])
                    if not isinstance(rows, list):
                        raise ECWError("Invalid job logs response")
                    logs.extend(rows)
                    next_cursor = page.get("next_cursor")
                    if not rows or next_cursor is None or next_cursor == cursor:
                        break
                    if type(next_cursor) is not int or next_cursor < cursor:
                        raise ECWError("Invalid job log cursor")
                    cursor = next_cursor
                else:
                    raise ECWError("Job logs exceeded the 64-page collection budget")
                evidence.write(prefix + "/logs.json", {"logs": logs, "next_cursor": cursor})
        except Exception as error:
            errors.append(f"{endpoint}: {error}")
    evidence.write(prefix + "/collection-errors.json", errors)
    return results, errors


def execute(client, booking_id, spec, run_id, metadata, config, evidence, record):
    payload = {**spec.payload, "booking_id": booking_id,
               "request_id": f"ecw-host-{run_id}-{spec.label}",
               "metadata": {**spec.payload.get("metadata", {}), **metadata,
                            "client": "ecw-ci-host", "run_id": run_id, "job_label": spec.label}}
    prefix = f"jobs/{spec.label}"
    evidence.write(prefix + "/request.json", payload)
    created = create_job(client, booking_id, payload)
    job_id = created["id"]
    record.update(id=job_id, status=created.get("status", "queued"))
    evidence.write(prefix + "/created.json", created)
    root = f"/v1/ci/jobs/{job_id}"
    failure = None
    job = created
    def observe(current):
        record["status"] = current.get("status")
        evidence.write(prefix + "/job.json", current)
    try:
        job = poll_job(client, job_id, min(config.job_timeout, spec.payload["duration_seconds"] + 60),
                       poll_interval=config.poll_interval, observe=observe)
    except Exception as error:
        failure = str(error)
    finally:
        results, collection_errors = _collect(client, root, prefix, evidence)
    if failure or collection_errors:
        raise ECWError(f"Job {spec.label}: " + "; ".join(([failure] if failure else []) + collection_errors))
    if (job.get("status") != "succeeded" or job.get("metadata") != payload["metadata"]
            or not isinstance(results, dict) or results.get("status") != "succeeded"
            or any(results.get("results", {}).get(c["id"], {}).get("success") is not True
                   for c in spec.payload["commands"])):
        raise ECWError(f"Job {spec.label} failed or returned incomplete results/metadata; inspect its evidence")
    try:
        record["checks"] = verify_checks(evidence.root / prefix / "artifacts.zip", spec.checks)
        evidence.write(prefix + "/checks.json", record["checks"])
    except Exception as error:
        evidence.write(prefix + "/checks.json", {"passed": False, "error": str(error)})
        raise


def cancel_queued(client, records, evidence):
    errors = []
    for record in records:
        if record.get("id") and record.get("status") not in TERMINAL:
            try:
                root = f"/v1/ci/jobs/{record['id']}"
                current = client.request(root)
                if current.get("status") == "queued":
                    current = client.request(root + "/cancel", method="POST")
                record["status"] = current.get("status")
                evidence.write(f"jobs/{record['label']}/cleanup.json", current)
                if current.get("status") not in TERMINAL:
                    errors.append(f"Job {record['id']} is still {current.get('status')}; the API cancels queued jobs only")
            except Exception as error:
                errors.append(f"Job {record['id']} cleanup: {error}")
    return errors
