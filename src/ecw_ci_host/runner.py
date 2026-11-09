"""Provider-independent orchestration shared by the CLI and Python callers."""

from dataclasses import asdict, dataclass, field, replace
import os
from pathlib import Path
import uuid

from .booking import Booking
from .select_board import select_board
from .client import ECWClient
from .config import RunConfig
from .evidence import Evidence
from .firmware import upload_and_flash
from . import hil, jobs


@dataclass
class RunResult:
    run_id: str
    output_dir: str
    status: str = "failed"
    booking_id: int | None = None
    booking_created: bool = False
    jobs: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def success(self):
        return self.status == "passed" and not self.errors

    @property
    def exit_code(self):
        return 130 if self.status == "interrupted" else 0 if self.success else 1

    def to_dict(self):
        return {**asdict(self), "success": self.success, "exit_code": self.exit_code}


def validate_run(config: RunConfig, *, require_firmware=True):
    config.validate(require_firmware=require_firmware)
    specs = jobs.load_specs(config.jobs_dir)
    values = hil.validate_csv(config.hil_sensor, config.hil_csv) if config.hil_sensor else None
    return specs, values


def run_test(config: RunConfig, *, api_key: str | None = None, client=None) -> RunResult:
    # Validate every project input before booking or changing real hardware.
    specs, values = validate_run(config)
    client = client or ECWClient(config.backend_url, api_key or os.environ.get("ECW_API_KEY", ""))
    run_id = uuid.uuid4().hex
    result = RunResult(run_id, str((Path(config.output_dir) / run_id).resolve()))
    evidence = Evidence(Path(result.output_dir), client.redact)
    lease = Booking(client, config, evidence)
    phase = "booking"
    try:
        selected = select_board(client, config.board, evidence)
        config = replace(config, board=selected["board_name"])
        lease.config = config
        required = max(config.minimum_remaining,
                       sum(spec.payload["duration_seconds"] for spec in specs) + 210
                       + (180 + 30 * ((len(values[0]) + 127) // 128) if values else 0))
        lease.acquire(required)
        if values:
            phase = "hil"
            hil.configure(client, lease.id, config.hil_sensor, values, evidence)
        phase = "firmware"
        firmware = upload_and_flash(client, lease.id, config.firmware, evidence)
        phase = "jobs"
        metadata = {**config.metadata, "board_name": config.board, "firmware_sha256": firmware["sha256"]}
        for spec in specs:
            record = {"label": spec.label, "status": "not_created"}
            result.jobs.append(record)
            jobs.execute(client, lease.id, spec, run_id, metadata, config, evidence, record)
        result.status = "passed"
    except (Exception, KeyboardInterrupt) as error:
        result.status = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        result.errors.append({"phase": phase, "message": client.redact(str(error) or type(error).__name__)})
    finally:
        result.booking_id, result.booking_created = lease.id, lease.owned_by_run
        if not result.success:
            for error in jobs.cancel_queued(client, result.jobs, evidence):
                result.errors.append({"phase": "job_cleanup", "message": client.redact(error)})
        try:
            lease.release()
        except Exception as error:
            result.errors.append({"phase": "release", "message": client.redact(str(error))})
        if result.errors and result.status == "passed":
            result.status = "failed"
        evidence.write("summary.json", result.to_dict())
    return result
