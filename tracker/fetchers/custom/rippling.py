"""Rippling: its own applicant system (ats.rippling.com) has a public board API with search."""

from __future__ import annotations

import httpx

from tracker.fetchers.base import FetchError, get_json, mentions_remote, register_custom
from tracker.models import Company, RawPosting

API = "https://ats.rippling.com/api/v2/board/rippling/jobs"
PAGE_SIZE = 100
MAX_PAGES = 10


def _location(loc: object) -> str:
    if not isinstance(loc, dict):
        return ""
    name = str(loc.get("name") or "")
    country = str(loc.get("country") or "")
    return f"{name}, {country}" if country and country not in name else name


def normalize(company: Company, items: list[object]) -> list[RawPosting]:
    postings = []
    for job in items:
        if not isinstance(job, dict) or not job.get("id") or not job.get("name"):
            raise FetchError("rippling: job without id or name")
        raw_locations = job.get("locations") if isinstance(job.get("locations"), list) else []
        locations = [text for text in (_location(loc) for loc in raw_locations) if text]
        remote = any(
            isinstance(loc, dict) and loc.get("workplaceType") == "REMOTE" for loc in raw_locations
        )
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=str(job["id"]),
                title=str(job["name"]).strip(),
                locations=locations,
                is_remote=remote or mentions_remote(*locations),
                url=str(job.get("url") or f"https://ats.rippling.com/rippling/jobs/{job['id']}"),
            )
        )
    return postings


@register_custom("rippling")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    items: list[object] = []
    for page in range(MAX_PAGES):
        payload = await get_json(
            client,
            API,
            params={"searchQuery": "intern", "page": page, "pageSize": PAGE_SIZE},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise FetchError("rippling: response has no items list")
        items += payload["items"]
        pages = payload.get("totalPages")
        if not isinstance(pages, int):
            raise FetchError("rippling: response has no totalPages")
        if page + 1 >= pages:
            break
    else:
        raise FetchError(f"rippling: more than {MAX_PAGES} pages of matches")
    return normalize(company, items)
