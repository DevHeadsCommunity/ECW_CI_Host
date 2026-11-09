"""Template storage-only upload, manifest verification, and returned filename."""

import hashlib
from pathlib import Path
import re

from .client import ECWError, require_okay


def upload_firmware(client, booking_id, firmware):
    firmware = Path(firmware)
    content = firmware.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    # Preserve the template's safe basename rule, adding a content fingerprint.
    stem = re.sub(r"[^A-Za-z0-9._]", "_", firmware.stem)[:35] or "firmware"
    code = f"{stem}_{digest[:16]}{firmware.suffix.lower()}"
    response = client.upload(booking_id, content, code)
    require_okay(response, "Firmware upload")
    manifest = client.request("/v1/artifacts/my-uploads", params={"booking_id": booking_id})
    items = manifest.get("items", []) if isinstance(manifest, dict) else []
    if not isinstance(items, list) or not any(
        isinstance(item, dict) and item.get("filename") == code for item in items
    ):
        raise ECWError("Uploaded firmware is missing from ECW storage; no flash was requested")
    return {"local_file": str(firmware), "stored_filename": code, "sha256": digest,
            "uploaded": True, "flashed": False}
