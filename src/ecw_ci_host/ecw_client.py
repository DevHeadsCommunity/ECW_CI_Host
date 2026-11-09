"""HTTP helpers extracted from the ECW template; provider output writers removed."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .errors import ECWError

# The default urllib User-Agent ("Python-urllib/x.y") is blocked by the WAF
# in front of the dev/staging backends, so every request needs a UA that
# doesn't match that bot signature.
USER_AGENT = "ecw-ci-smoke-script"


def request_json(
    url: str,
    api_key: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    body: dict | None = None,
    timeout: float = 10,
    opener=None,
) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = {"X-API-Key": api_key, "User-Agent": USER_AGENT}
    data = None
    if body is not None:
        data = json.dumps(body, allow_nan=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with _open(request, api_key, timeout, opener) as response:
        return _json_response(response)


def request_bytes(url: str, api_key: str, *, timeout: float = 30, opener=None) -> bytes:
    request = urllib.request.Request(
        url, headers={"X-API-Key": api_key, "User-Agent": USER_AGENT}
    )
    with _open(request, api_key, timeout, opener) as response:
        data = response.read(ARTIFACT_LIMIT + 1)
        if len(data) > ARTIFACT_LIMIT:
            raise ECWError("Artifact response exceeds 64 MiB")
        return data


def upload_file(
    url: str,
    api_key: str,
    path: Path | None,
    filename: str,
    *,
    params: dict | None = None,
    timeout: float = 60,
    content: bytes | None = None,
    opener=None,
) -> dict:
    """Store a file through the multipart upload API; this never flashes it."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    boundary = f"ecw-ci-{uuid.uuid4().hex}"
    data = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode("ascii") + (content if content is not None else path.read_bytes()) + f"\r\n--{boundary}--\r\n".encode("ascii")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "X-API-Key": api_key,
            "User-Agent": USER_AGENT,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with _open(request, api_key, timeout, opener) as response:
        return _json_response(response)


JSON_LIMIT = 4 * 1024 * 1024
ARTIFACT_LIMIT = 64 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(request, api_key, timeout, opener=None):
    try:
        return (opener or urllib.request.build_opener(NoRedirect())).open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        try:
            detail = error.read(4096).decode("utf-8", errors="replace")
        finally:
            error.close()
        detail = detail.replace(api_key, "[redacted]")
        path = urllib.parse.urlsplit(request.full_url).path
        raise ECWError(f"{request.method} {path}: HTTP {error.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ECWError(str(error).replace(api_key, "[redacted]")) from None


def _json_response(response):
    data = response.read(JSON_LIMIT + 1)
    if len(data) > JSON_LIMIT:
        raise ECWError("JSON response exceeds the configured size limit")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise ECWError("API returned invalid JSON") from None
