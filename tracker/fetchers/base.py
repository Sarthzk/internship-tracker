"""The fetcher interface and the registry mapping `ats` (or a custom company slug) to a fetcher.

A fetcher only fetches and normalizes: no filtering, no diffing. If a response does not have
the expected shape it must raise `FetchError`, never return an empty list, because an empty
list is read as "this company has no postings" and can eventually close listings.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime

import httpx

from tracker.models import AtsType, Company, RawPosting

FetchFn = Callable[[Company, httpx.AsyncClient], Awaitable[list[RawPosting]]]

FETCHERS: dict[str, FetchFn] = {}
CUSTOM_FETCHERS: dict[str, FetchFn] = {}  # keyed by company slug


class FetchError(Exception):
    """The site answered, but not with something we can trust (bad status or shape)."""


def register(ats: AtsType) -> Callable[[FetchFn], FetchFn]:
    def decorator(fn: FetchFn) -> FetchFn:
        FETCHERS[ats] = fn
        return fn

    return decorator


def register_custom(company_slug: str) -> Callable[[FetchFn], FetchFn]:
    def decorator(fn: FetchFn) -> FetchFn:
        CUSTOM_FETCHERS[company_slug] = fn
        return fn

    return decorator


def get_fetcher(company: Company) -> FetchFn | None:
    if company.ats == AtsType.custom:
        return CUSTOM_FETCHERS.get(company.slug)
    return FETCHERS.get(company.ats)


async def request_json(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> object:
    response = await client.request(method, url, **kwargs)
    if response.status_code != 200:
        raise FetchError(f"HTTP {response.status_code} from {response.url.host}")
    try:
        return response.json()
    except ValueError as exc:
        raise FetchError(f"invalid JSON from {response.url.host}") from exc


async def get_json(client: httpx.AsyncClient, url: str, **kwargs) -> object:
    return await request_json(client, "GET", url, **kwargs)


async def post_json(client: httpx.AsyncClient, url: str, **kwargs) -> object:
    return await request_json(client, "POST", url, **kwargs)


def parse_iso_date(value: object) -> date | None:
    """`2026-10-01T10:00:00-04:00` (or `...Z`) → the UTC date; anything else → None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date()


def parse_epoch_ms_date(value: object) -> date | None:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).date()


def mentions_remote(*texts: str | None) -> bool:
    return any(t and "remote" in t.lower() for t in texts)
