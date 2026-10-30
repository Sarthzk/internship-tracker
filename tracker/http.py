"""Shared, polite HTTP client (CLAUDE.md rule 4).

Politeness lives in a transport wrapper, so fetchers can use a plain `httpx.AsyncClient`:
at most one in-flight request per host, a minimum delay between requests to the same host,
and retries with exponential backoff on network errors, 429 and 5xx only.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

import httpx

from tracker import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"internship-tracker/{__version__} (+https://github.com/Sarthzk/internship-tracker)"
TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
MAX_BACKOFF_SECONDS = 30.0
RATE_LIMIT_FACTOR = 5


def _is_retryable(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "").strip()
    return float(value) if value.isdigit() else None


class PoliteTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        inner: httpx.AsyncBaseTransport | None = None,
        *,
        delay: float = 1.0,
        backoff: float = 1.0,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._inner = inner or httpx.AsyncHTTPTransport()
        self._delay = delay
        self._backoff = backoff
        self._max_attempts = max_attempts
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_request: dict[str, float] = {}

    async def _wait_for_turn(self, host: str) -> None:
        loop = asyncio.get_running_loop()
        wait = self._last_request.get(host, float("-inf")) + self._delay - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)

    def _mark(self, host: str) -> None:
        self._last_request[host] = asyncio.get_running_loop().time()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        async with self._locks[host]:
            for attempt in range(self._max_attempts):
                last_attempt = attempt == self._max_attempts - 1
                await self._wait_for_turn(host)
                try:
                    response = await self._inner.handle_async_request(request)
                except httpx.TransportError as exc:
                    self._mark(host)
                    if last_attempt:
                        raise
                    log.info("%s %s: %s, retrying", request.method, host, type(exc).__name__)
                    await asyncio.sleep(self._backoff * 2**attempt)
                    continue
                self._mark(host)
                if last_attempt or not _is_retryable(response.status_code):
                    return response
                wait = _retry_after(response)
                if wait is None:
                    # A rate limiter needs real time to cool down, so 429 waits 5x longer
                    # (5 s, then 10 s) than a server error (1 s, then 2 s).
                    factor = RATE_LIMIT_FACTOR if response.status_code == 429 else 1
                    wait = self._backoff * factor * 2**attempt
                await response.aclose()
                log.info("%s %s: HTTP %d, retrying", request.method, host, response.status_code)
                await asyncio.sleep(min(wait, MAX_BACKOFF_SECONDS))
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        await self._inner.aclose()


def make_client(
    *,
    inner: httpx.AsyncBaseTransport | None = None,
    delay: float = 1.0,
    backoff: float = 1.0,
) -> httpx.AsyncClient:
    """The one client every fetcher uses. Tests pass `delay=0, backoff=0`."""
    return httpx.AsyncClient(
        transport=PoliteTransport(inner, delay=delay, backoff=backoff),
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
    )
