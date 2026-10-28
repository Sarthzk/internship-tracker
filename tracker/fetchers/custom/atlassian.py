"""Atlassian: one JSON array of every open role (about 2.5 MB, no server-side filtering)."""

from __future__ import annotations

import httpx

from tracker.fetchers.base import FetchError, get_json, mentions_remote, register_custom
from tracker.models import Company, RawPosting

API = "https://www.atlassian.com/endpoint/careers/listings"


def normalize(company: Company, payload: object) -> list[RawPosting]:
    if not isinstance(payload, list):
        raise FetchError("atlassian: response is not a list")
    postings = []
    for job in payload:
        if not isinstance(job, dict) or job.get("id") is None or not job.get("title"):
            raise FetchError("atlassian: job without id or title")
        portal = job.get("portalJobPost") if isinstance(job.get("portalJobPost"), dict) else {}
        url = portal.get("portalUrl") or job.get("applyUrl")
        if not url:
            raise FetchError("atlassian: job without a URL")
        locations = [loc for loc in job.get("locations") or [] if isinstance(loc, str) and loc]
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=str(job["id"]),
                title=str(job["title"]).strip(),
                locations=locations,
                is_remote=mentions_remote(*locations),
                url=url,
            )
        )
    return postings


@register_custom("atlassian")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    return normalize(company, await get_json(client, API))
