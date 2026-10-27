"""Fetcher for lever job boards.

`GET https://api.lever.co/v0/postings/{site}?mode=json` returns a list of every posting,
descriptions included (kept in memory only).
"""

from __future__ import annotations

import httpx

from tracker.fetchers.base import (
    FetchError,
    get_json,
    mentions_remote,
    parse_epoch_ms_date,
    register,
)
from tracker.models import AtsType, Company, RawPosting

API = "https://api.lever.co/v0/postings/{site}"


def normalize(company: Company, payload: object) -> list[RawPosting]:
    if not isinstance(payload, list):
        raise FetchError("lever: response is not a list")
    postings = []
    for job in payload:
        categories = job.get("categories") or {}
        locations = [loc for loc in categories.get("allLocations") or [] if loc]
        if not locations and categories.get("location"):
            locations = [categories["location"]]
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="lever",
                external_id=str(job["id"]),
                title=(job.get("text") or "").strip(),
                locations=locations,
                is_remote=job.get("workplaceType") == "remote" or mentions_remote(*locations),
                url=job["hostedUrl"],
                date_posted=parse_epoch_ms_date(job.get("createdAt")),
                description=job.get("descriptionPlain"),
            )
        )
    return postings


@register(AtsType.lever)
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    url = API.format(site=company.ats_config["site"])
    return normalize(company, await get_json(client, url, params={"mode": "json"}))
