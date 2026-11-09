"""Booking ownership, identity, UTC windows, and release."""

from datetime import datetime, timezone
import math

from .client import ECWError, require_okay
from .find_or_create_booking import find_or_create_booking
from .wait_for_booking import _parseDatetime as timestamp, wait_for_booking


def positive_id(value):
    if type(value) is not int or value <= 0:
        raise ECWError("API response is missing a positive integer id")
    return value


class Booking:
    def __init__(self, client, config, evidence):
        self.client, self.config, self.evidence = client, config, evidence
        self.id = config.booking_id
        self.owned_by_run = False
        self.identity = None

    def acquire(self, required_seconds):
        if self.id is None:
            response, created = find_or_create_booking(self.client, self.config.board,
                                                       reuse_existing=self.config.reuse_existing)
            self.id = positive_id(response.get("id"))
            self.owned_by_run = created
        self.evidence.write("reservation.json", {"id": self.id, "created_by_run": self.owned_by_run})
        extension_attempted = False

        def observe(booking):
            nonlocal extension_attempted
            self.evidence.write("booking-response.json", booking)
            self.verify_identity(booking)
            status = str(booking.get("status", "")).lower()
            now = datetime.now(timezone.utc)
            remaining = (timestamp(booking["end_utc"]) - now).total_seconds()
            if status in {"cancelled", "cleanedup", "failed"} or remaining <= 0:
                return True  # The extracted wait loop reports the terminal reason.
            if remaining <= required_seconds:
                if self.owned_by_run and not extension_attempted:
                    extension_attempted = True
                    minutes = min(30, max(10, math.ceil((required_seconds - remaining + 60) / 60)))
                    response = self.client.request("/extend_booking", method="POST",
                                                   params={"booking_id": self.id, "duration": minutes})
                    if response.get("id") != self.id:
                        raise ECWError("Booking extension response does not identify this booking")
                    self.evidence.write("booking-extension.json", response)
                    return False
                raise ECWError(f"Booking needs more than {required_seconds} seconds remaining")
            return True

        return wait_for_booking(self.client, self.id, self.config.booking_timeout,
                                poll_interval=self.config.poll_interval, observe=observe)

    def verify_identity(self, booking):
        if booking.get("id") != self.id:
            raise ECWError("Booking response id does not match the requested booking")
        board_id = positive_id(booking.get("board_id"))
        name = booking.get("board_name")
        if name is not None and name != self.config.board:
            raise ECWError("Booking is for a different board type")
        if self.identity is None:
            board = self.client.request("/board", params={"board_id": board_id})
            type_id = positive_id(board.get("board_type_id"))
            board_type = self.client.request("/board_type", params={"board_type_id": type_id})
            if (board.get("id") != board_id or board_type.get("id") != type_id
                    or board_type.get("board_name") != self.config.board or board_type.get("is_mcu") is not True):
                raise ECWError("Booked board metadata does not identify the requested MCU")
            self.identity = {"board_id": board_id, "board_type_id": type_id, "board_name": self.config.board}
            self.evidence.write("board-identity.json", self.identity)
        elif self.identity["board_id"] != board_id:
            raise ECWError("Booked hardware changed while waiting")

    def release(self):
        if self.id is not None and self.owned_by_run:
            response = self.client.request("/cancel-booking", params={"booking_id": self.id})
            self.evidence.write("release.json", response)
            require_okay(response, "Booking release")
