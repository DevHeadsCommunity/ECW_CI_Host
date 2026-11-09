"""Portable inputs/evidence around the template's HIL functions."""

from pathlib import Path
from .configure_hil import configure as _configure, prepare_and_wait as prepare
from .hil_csv import read_csv, sensor_profile


def validate_csv(sensor: str, csv_path: Path):
    return read_csv(Path(csv_path), sensor_profile(sensor))


def configure(client, booking_id, sensor, values, evidence):
    report = {"status": "configuring", "sensor": sensor, "sent_words": 0}
    try:
        _configure(client, booking_id, sensor, values, report)
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        evidence.write("hil.json", report)
    return report
