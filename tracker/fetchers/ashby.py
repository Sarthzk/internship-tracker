"""Fetcher for ashby job boards.

`GET https://api.ashbyhq.com/posting-api/job-board/{site}` returns `{"jobs": [...]}`,
descriptions included (kept in memory only). Unlisted jobs are skipped.
"""

from __future__ import annotations

import httpx

from tracker.fetchers.base import FetchError, get_json, mentions_remote, parse_iso_date, register
from tracker.models import AtsType, Company, RawPosting

API = "https://api.ashbyhq.com/posting-api/job-board/{site}"


def normalize(company: Company, payload: object) -> list[RawPosting]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise FetchError("ashby: response has no 'jobs' list")
    postings = []
    for job in payload["jobs"]:
        if job.get("isListed") is False:
            continue
        locations = [job.get("location") or ""]
        locations += [s.get("location") or "" for s in job.get("secondaryLocations") or []]
        locations = [loc for loc in locations if loc]
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="ashby",
                external_id=str(job["id"]),
                title=(job.get("title") or "").strip(),
                locations=locations,
                is_remote=bool(job.get("isRemote")) or mentions_remote(*locations),
                url=job["jobUrl"],
                date_posted=parse_iso_date(job.get("publishedAt")),
                description=job.get("descriptionPlain"),
            )
        )
    return postings


@register(AtsType.ashby)
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    url = API.format(site=company.ats_config["site"])
    return normalize(company, await get_json(client, url))
