"""Board discovery extracted from select_board.py in the ECW template."""

from .errors import ECWError


def select_board(client, search, evidence=None):
    board_types_response = client.request("/board_types", params={"page_no": "1", "page_size": "100"})
    if evidence is not None:
        evidence.write("board-types.json", board_types_response)
    board_types = board_types_response
    if isinstance(board_types, dict):
        board_types = (board_types.get("items") or board_types.get("board_types")
                       or board_types.get("results") or board_types.get("data") or [])
    if not isinstance(board_types, list):
        raise ECWError("Invalid board catalog response")
    matches = [board_type for board_type in board_types
               if search.lower() in str(board_type.get("board_name", "")).lower()]
    exact = [row for row in matches if row.get("board_name", "").casefold() == search.casefold()]
    matches = exact or matches
    if len(matches) != 1 or not matches[0].get("board_name"):
        raise ECWError(f"Board name must match exactly one catalog entry: {search}")
    return matches[0]
