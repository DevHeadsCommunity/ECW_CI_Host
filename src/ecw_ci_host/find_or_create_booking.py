"""Template booking discovery/creation with explicit ownership return values."""

def _findExistingBooking(client, board_name: str) -> dict | None:
    bookings = client.request(
        "/bookings/me",
        params={"page_no": "1", "page_size": "100"},
    )
    for booking in bookings:
        if str(booking.get("board_name", "")).lower() == board_name.lower():
            return booking
    return None


def _createBooking(client, board_name: str) -> dict:
    return client.request(
        "/auto-bookings",
        method="POST",
        params={"board_name": board_name},
    )



def find_or_create_booking(client, board_name, *, reuse_existing=True):
    existing = _findExistingBooking(client, board_name) if reuse_existing else None
    if existing is not None:
        return existing, False
    return _createBooking(client, board_name), True
