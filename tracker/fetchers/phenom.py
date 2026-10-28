"""Fetcher for Phenom career sites (`POST https://{host}/widgets`, the site's own search call).

We search for "intern" restricted to India, 50 results per page. The response is
`refineSearch.data.jobs`; `totalHits` says when to stop. The public job page is
`https://{host}/{locale}/job/{jobId}` where `locale` (default `us/en`) is the site's URL prefix.
"""

from __future__ import annotations

import httpx

from tracker.fetchers.base import (
    FetchError,
    mentions_remote,
    parse_iso_date,
    post_json,
    register,
)
from tracker.models import AtsType, Company, RawPosting

PAGE_SIZE = 50
MAX_PAGES = 10


def _body(offset: int) -> dict:
    return {
        "lang": "en_us",
        "deviceType": "desktop",
        "country": "us",
        "pageName": "search-results",
        "ddoKey": "refineSearch",
        "sortBy": "",
        "subsearch": "",
        "from": offset,
        "jobs": True,
        "counts": True,
        "all_fields": ["category", "country", "state", "city", "type"],
        "size": PAGE_SIZE,
        "clearAll": False,
        "jdsource": "facets",
        "isSliderEnable": False,
        "pageId": "page11",
        "siteType": "external",
        "keywords": "intern",
        "global": True,
        "selected_fields": {"country": ["India"]},
        "sort": {"order": "desc", "field": "postedDate"},
        "locationData": {},
    }


def normalize(company: Company, host: str, locale: str, jobs: list[object]) -> list[RawPosting]:
    postings = []
    for job in jobs:
        if not isinstance(job, dict) or not job.get("jobId") or not job.get("title"):
            raise FetchError("phenom: job without jobId or title")
        raw = job.get("multi_location")
        locations = (
            [loc for loc in raw if isinstance(loc, str) and loc] if isinstance(raw, list) else []
        )
        if not locations:
            single = job.get("cityStateCountry") or job.get("location")
            locations = [str(single)] if single else []
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="phenom",
                external_id=str(job["jobId"]),
                title=str(job["title"]).strip(),
                locations=locations,
                is_remote=mentions_remote(*locations),
                url=f"https://{host}/{locale}/job/{job['jobId']}",
                date_posted=parse_iso_date(job.get("postedDate")),
            )
        )
    return postings


async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    host = company.ats_config["host"]
    locale = company.ats_config.get("locale", "us/en")
    jobs: list[object] = []
    total = 0
    for page in range(MAX_PAGES):
        payload = await post_json(client, f"https://{host}/widgets", json=_body(page * PAGE_SIZE))
        search = payload.get("refineSearch") if isinstance(payload, dict) else None
        data = search.get("data") if isinstance(search, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise FetchError("phenom: response has no refineSearch.data.jobs")
        if not isinstance(search.get("totalHits"), int):
            raise FetchError("phenom: response has no totalHits")
        total = search["totalHits"]
        jobs += data["jobs"]
        if len(jobs) >= total or not data["jobs"]:
            break
    else:
        raise FetchError(f"phenom: more than {MAX_PAGES * PAGE_SIZE} matches")
    if len(jobs) < total:
        raise FetchError(f"phenom: got {len(jobs)} of {total} jobs")
    return normalize(company, host, locale, jobs)


register(AtsType.phenom)(fetch)
