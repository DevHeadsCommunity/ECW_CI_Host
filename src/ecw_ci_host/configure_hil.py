"""Template HIL implementation; inputs and evidence replace provider variables."""

import json
import queue
import threading
import time
from .errors import ECWError

PREPARE_TIMEOUT_SECONDS = 180
MAX_WORDS_PER_REQUEST = 128


def okay(response, operation):
    if not isinstance(response, dict) or response.get("status") != "okay":
        raise ECWError(f"HIL {operation} did not report success.")


def prepare_and_wait(client, booking_id, configuration_id,
                     *, timeout=PREPARE_TIMEOUT_SECONDS):
    """Wait for the same programming/activation response used by the frontend."""
    deadline = time.monotonic() + timeout
    results = queue.Queue(maxsize=1)

    def remaining():
        value = deadline - time.monotonic()
        if value <= 0:
            raise ECWError("HIL preparation did not become active within 180 seconds.")
        return value

    def run():
        try:
            context = {"booking_id": booking_id, "configuration_id": configuration_id}
            response = client.request("/v1/peripheral-prepare",
                                    method="POST", params=context, timeout=remaining())
            okay(response, "preparation")
            remaining()
            results.put((response, None))
        except Exception as error:
            results.put((None, error))

    # A slow response body cannot extend the client deadline. A timed-out worker
    # cannot send CSV values or issue a second preparation request. The existing
    # API returns success only after image preparation and activation succeed.
    worker = threading.Thread(target=run, daemon=True, name="hil-preparation")
    worker.start()
    try:
        state, error = results.get(timeout=max(0, deadline - time.monotonic()))
    except queue.Empty:
        raise ECWError("HIL preparation did not become active within 180 seconds.") from None
    if time.monotonic() > deadline:
        raise ECWError("HIL preparation did not become active within 180 seconds.")
    if error is not None:
        raise error
    return state


def configure(client, booking_id, name, values, report):
    words, samples = values
    available = client.request("/v1/peripherals-list",
                             params={"booking_id": booking_id})
    if not isinstance(available, list):
        raise ECWError("HIL sensor list response is invalid.")
    matches = [row for row in available if str(row.get("name", "")).strip().casefold() == name.casefold()]
    if len(matches) != 1:
        raise ECWError(f"HIL sensor name must match exactly one available sensor name: {name!r}.")
    sensor_id = matches[0]["id"]
    context = {"booking_id": booking_id}
    selected = client.request("/v1/peripherals", params=context)
    if not isinstance(selected, list):
        raise ECWError("HIL selection response is invalid.")
    if len(selected) != 1 or selected[0].get("id") != sensor_id:
        configs = {str(sensor_id): {"name": "ci_hil", "elements": []}}
        okay(client.request("/v1/peripherals", method="PUT",
                          params={**context, "peripheral_config": json.dumps(configs)},
                          body=[sensor_id]), "selection")
        selected = client.request("/v1/peripherals", params=context)
    if (not isinstance(selected, list) or len(selected) != 1 or selected[0].get("id") != sensor_id
            or not isinstance(selected[0].get("configuration_id"), int)):
        raise ECWError("HIL selection is missing its saved configuration ID.")
    configuration_id = selected[0]["configuration_id"]
    report.update(sensor=name, samples=samples, words=len(words),
                  booking_id=booking_id, configuration_id=configuration_id, sent_words=0)
    report["readiness"] = prepare_and_wait(client, booking_id, configuration_id)
    for address in range(0, len(words), MAX_WORDS_PER_REQUEST):
        chunk = words[address:address + MAX_WORDS_PER_REQUEST]
        okay(client.request("/v1/peripheral-program-value", method="POST",
                          params={**context, "configuration_id": configuration_id},
                          body={"address": address, "type": "string",
                                "value": "\n".join(f"{word:04X}" for word in chunk)}, timeout=30),
             "CSV value write")
        report["sent_words"] += len(chunk)
    report["status"] = "succeeded"
