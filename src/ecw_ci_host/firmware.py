"""Compose the two extracted template stages without conflating their success."""

from .upload_firmware import upload_firmware
from .flash_firmware import flash_firmware


def upload_and_flash(client, booking_id, firmware, evidence):
    report = upload_firmware(client, booking_id, firmware)
    evidence.write("firmware.json", report)
    flash_firmware(client, booking_id, report["stored_filename"])
    report["flashed"] = True
    evidence.write("firmware.json", report)
    return report
