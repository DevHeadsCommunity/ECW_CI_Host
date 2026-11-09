"""Template explicit flash request, with a returned stored filename."""

import re
from .client import require_okay


def flash_firmware(client, booking_id, code):
    if not re.fullmatch(r"[A-Za-z0-9._]{1,60}\.(bin|hex)", code):
        raise ValueError("Flash requires the stored filename returned by upload")
    # As in the template, this side effect is never automatically retried.
    response = client.request("/v1/artifacts/my-uploads", method="POST",
                              params={"booking_id": booking_id, "code": code}, timeout=180)
    require_okay(response, "Explicit firmware flash")
    return response
