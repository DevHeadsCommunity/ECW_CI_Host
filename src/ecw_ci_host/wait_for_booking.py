"""Booking activation loop extracted from the template's wait_for_booking.py."""

from datetime import datetime, timezone
import time
from .errors import ECWError


def _parseDatetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def wait_for_booking(client, booking_id, timeout_seconds, *, poll_interval=2, observe=None):
    deadline = time.monotonic() + timeout_seconds
    while True:
        if time.monotonic() >= deadline:
            raise ECWError(f"Booking {booking_id} did not become active within {timeout_seconds} seconds")
        booking = client.request("/booking", params={"booking_id": booking_id})
        if observe is not None and observe(booking) is False:
            continue
        start = _parseDatetime(booking["start_utc"])
        end = _parseDatetime(booking["end_utc"])
        status = str(booking.get("status", "")).lower()
        now = datetime.now(timezone.utc)
        if start <= now < end and status == "active":
            return booking
        if status in {"cancelled", "cleanedup", "failed"}:
            raise ECWError(f"Booking {booking_id} is {status}; it cannot become active")
        if now >= end:
            raise ECWError(f"Booking {booking_id} ended before it became active")
        wait_seconds = min(max((start - now).total_seconds() + 0.5, 1), poll_interval,
                           max(0, deadline - time.monotonic()))
        time.sleep(wait_seconds)
