"""Shared HTTP fetch helper: retries with exponential backoff, raw-response capture.

Gov sites drop connections and time out routinely (see docs/sources/README.md);
every plugin fetch goes through request_raw() so retry behavior is uniform.
"""

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .schema import RawResponse

IST = ZoneInfo("Asia/Kolkata")
UA = "india-grid-map/0.1 (open data project; contact: adityamsawant07@gmail.com)"

MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 2.0  # 2s, 4s between attempts


def make_client(*, verify: bool = True) -> httpx.Client:
    return httpx.Client(
        verify=verify,
        headers={"User-Agent": UA},
        timeout=30,
        follow_redirects=True,
    )


def request_raw(
    client: httpx.Client,
    source: str,
    method: str,
    url: str,
    *,
    meta: dict[str, Any],
    json: Any | None = None,
) -> RawResponse:
    """Fetch with retries; always returns a RawResponse (error captured in meta)."""
    last_error = ""
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = client.request(method, url, json=json)
        except httpx.HTTPError as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(BACKOFF_BASE_S * 2**attempt)
            continue
        if resp.status_code >= 500 and attempt < MAX_ATTEMPTS - 1:
            last_error = f"HTTP {resp.status_code}"
            time.sleep(BACKOFF_BASE_S * 2**attempt)
            continue
        return RawResponse(
            source=source,
            endpoint=url,
            fetched_at=datetime.now(IST),
            http_status=resp.status_code,
            content_type=resp.headers.get("content-type"),
            body=resp.content,
            meta={**meta, "attempts": attempt + 1},
        )
    return RawResponse(
        source=source,
        endpoint=url,
        fetched_at=datetime.now(IST),
        http_status=None,
        body=b"",
        meta={**meta, "error": last_error, "attempts": MAX_ATTEMPTS},
    )
