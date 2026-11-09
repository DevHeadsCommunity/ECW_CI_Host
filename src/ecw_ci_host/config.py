"""Project configuration; paths in a file are relative to that file."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
import json
from pathlib import Path
import tomllib

from .client import FIRMWARE_LIMIT, validate_url


@dataclass(frozen=True)
class RunConfig:
    board: str
    firmware: Path
    jobs_dir: Path
    output_dir: Path = Path("artifacts")
    backend_url: str = "https://plovdiv.edgebench.io/api"
    booking_id: int | None = None
    reuse_existing: bool = True
    booking_timeout: float = 900
    job_timeout: float = 600
    poll_interval: float = 2
    minimum_remaining: int = 360
    hil_sensor: str | None = None
    hil_csv: Path | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path, **overrides):
        path = Path(path).resolve()
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text())
        else:
            data = tomllib.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Run configuration must be an object")
        unknown = set(data) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown run configuration fields: {', '.join(sorted(unknown))}")
        for key in ("firmware", "jobs_dir", "output_dir", "hil_csv"):
            if key in data and data[key] is not None:
                data[key] = (path.parent / data[key]).resolve()
        data.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**data)

    def validate(self, *, require_firmware=True):
        validate_url(self.backend_url)
        if not isinstance(self.board, str) or not self.board.strip():
            raise ValueError("board must be the exact ECW board type name")
        if self.booking_id is not None and (type(self.booking_id) is not int or self.booking_id <= 0):
            raise ValueError("booking_id must be a positive integer")
        if type(self.reuse_existing) is not bool:
            raise ValueError("reuse_existing must be a boolean")
        for name in ("booking_timeout", "job_timeout", "poll_interval", "minimum_remaining"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 < value <= 86400:
                raise ValueError(f"{name} must be between 0 and 86400 seconds")
        if not isinstance(self.metadata, dict) or len(json.dumps(self.metadata, allow_nan=False).encode()) > 2048:
            raise ValueError("metadata must be a JSON object of at most 2048 bytes")
        if bool(self.hil_sensor) != bool(self.hil_csv):
            raise ValueError("Set both hil_sensor and hil_csv, or neither")
        if self.hil_csv and not Path(self.hil_csv).is_file():
            raise ValueError("HIL CSV does not exist")
        if Path(self.firmware).suffix.lower() not in {".bin", ".hex"}:
            raise ValueError("First version accepts MCU .bin and .hex firmware")
        if require_firmware and (not Path(self.firmware).is_file()
                                 or not 0 < Path(self.firmware).stat().st_size <= FIRMWARE_LIMIT):
            raise ValueError("Build a nonempty firmware file of at most 32 MiB before running")
        if not Path(self.jobs_dir).is_dir():
            raise ValueError("jobs_dir does not exist")
