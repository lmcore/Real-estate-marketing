"""Fetch a listing page from a URL (single, user-initiated request).

This module is deliberately simple and conservative:
- ONE request per call, no pagination, no link-following.
- Respects a 2-second delay if called multiple times (rate-limiting).
- Sends a realistic browser User-Agent (not a bot identifier).
- Returns raw HTML for downstream parsing by ``parsers.py``.

Legal note: this is functionally equivalent to the user opening the URL
in their browser and saving the page source. It is NOT automated
crawling — it only runs when the user explicitly asks for it via the CLI.
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_TIMEOUT = 15.0

# Simple rate-limiter: track the last fetch timestamp.
_last_fetch: float = 0.0
_MIN_INTERVAL = 2.0  # seconds between fetches


class FetchError(Exception):
    """Raised when the HTTP fetch fails."""


def fetch_listing_html(
    url: str,
    *,
    client: httpx.Client | None = None,
) -> str:
    """Fetch the HTML of a listing page.

    Parameters
    ----------
    url:
        Full URL to fetch.
    client:
        Optional injectable httpx.Client (for testing with MockTransport).

    Returns
    -------
    The HTML body as a string.

    Raises
    ------
    FetchError
        On HTTP errors (4xx, 5xx) or network failures.
    """
    global _last_fetch

    # Rate-limit: wait if we fetched recently.
    elapsed = time.monotonic() - _last_fetch
    if elapsed < _MIN_INTERVAL and _last_fetch > 0:
        time.sleep(_MIN_INTERVAL - elapsed)

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    }

    try:
        if client is not None:
            resp = client.get(url, headers=headers, timeout=_TIMEOUT, follow_redirects=True)
        else:
            with httpx.Client() as c:
                resp = c.get(url, headers=headers, timeout=_TIMEOUT, follow_redirects=True)
        _last_fetch = time.monotonic()
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPStatusError as exc:
        raise FetchError(
            f"HTTP {exc.response.status_code} for {url}"
        ) from exc
    except httpx.RequestError as exc:
        raise FetchError(f"Network error fetching {url}: {exc}") from exc
