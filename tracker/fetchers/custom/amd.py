"""AMD: iCIMS "Jibe" job API. `keywords=intern` returns every intern role worldwide (~100), and
the `location` filter does not understand "India", so India is picked out by the filters later."""

from __future__ import annotations

import httpx

from tracker.fetchers.base import (
    FetchError,
    get_json,
    mentions_remote,
    parse_iso_date,
    register_custom,
)
from tracker.models import Company, RawPosting

API = "https://careers.amd.com/api/jobs"
PAGE_SIZE = 100
MAX_PAGES = 10


def normalize(company: Company, jobs: list[object]) -> list[RawPosting]:
    postings = []
    for item in jobs:
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict) or not data.get("req_id") or not data.get("title"):
            raise FetchError("amd: job without req_id or title")
        place = [data.get("full_location"), data.get("country")]
        locations = [", ".join(str(p) for p in place if p)]
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=str(data["req_id"]),
                title=str(data["title"]).strip(),
                locations=[loc for loc in locations if loc],
                is_remote=mentions_remote(*locations),
                url=f"https://careers.amd.com/careers-home/jobs/{data['slug']}"
                if data.get("slug")
                else f"https://careers.amd.com/careers-home/jobs/{data['req_id']}",
                date_posted=parse_iso_date(data.get("posted_date")),
            )
        )
    return postings


@register_custom("amd")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    jobs: list[object] = []
    total = None
    for page in range(1, MAX_PAGES + 1):
        payload = await get_json(
            client, API, params={"keywords": "intern", "page": page, "limit": PAGE_SIZE}
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise FetchError("amd: response has no jobs list")
        if not isinstance(payload.get("totalCount"), int):
            raise FetchError("amd: response has no totalCount")
        total = payload["totalCount"]
        jobs += payload["jobs"]
        if len(jobs) >= total or not payload["jobs"]:
            break
    else:
        raise FetchError(f"amd: more than {MAX_PAGES * PAGE_SIZE} matches")
    if total is not None and len(jobs) < total:
        raise FetchError(f"amd: got {len(jobs)} of {total} jobs")
    return normalize(company, jobs)
