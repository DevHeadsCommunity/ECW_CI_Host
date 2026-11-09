"""Object adapter over the transport extracted from the ECW template."""

from pathlib import Path
import re
import urllib.parse
import urllib.request

from . import ecw_client
from .errors import ECWError

FIRMWARE_LIMIT = 32 * 1024 * 1024


def validate_url(value):
    url = urllib.parse.urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ValueError("backend_url must be an HTTPS API URL without credentials, query, or fragment")


class ECWClient:
    def __init__(self, base_url, api_key):
        validate_url(base_url)
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Set ECW_API_KEY to a key issued by the selected ECW environment")
        self.base_url, self._api_key = base_url.rstrip("/"), api_key
        self._opener = urllib.request.build_opener(ecw_client.NoRedirect())

    def redact(self, value):
        return value.replace(self._api_key, "[redacted]")

    def _url(self, path):
        if not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
            raise ValueError("API paths must be absolute paths; pass query values through params")
        return self.base_url + path

    def request(self, path, *, method="GET", params=None, body=None, timeout=30):
        return ecw_client.request_json(self._url(path), self._api_key, method=method,
                                      params=params, body=body, timeout=timeout, opener=self._opener)

    def upload(self, booking_id, content, filename):
        if not isinstance(content, bytes) or not 0 < len(content) <= FIRMWARE_LIMIT:
            raise ValueError("Firmware must contain between 1 byte and 32 MiB")
        if not re.fullmatch(r"[A-Za-z0-9._]{1,64}", filename):
            raise ValueError("Stored filename must be a backend-safe basename of at most 64 characters")
        return ecw_client.upload_file(self._url("/upload"), self._api_key, None, filename,
                                      params={"booking_id": booking_id}, content=content,
                                      timeout=180, opener=self._opener)

    def download(self, path, destination):
        data = ecw_client.request_bytes(self._url(path), self._api_key, timeout=60, opener=self._opener)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(destination)


def require_okay(response, operation):
    if not isinstance(response, dict) or response.get("status") != "okay":
        raise ECWError(f"{operation} did not report success")
