"""Fetcher for SmartRecruiters company boards.

`GET https://api.smartrecruiters.com/v1/companies/{company_id}/postings?q=intern&country=in`
returns `content[]` and `totalFound`; the server already narrows to India + "intern". Page with
`offset`. Note SmartRecruiters answers 200 with an empty list for company ids that do not exist,
so a wrong `company_id` looks like "no postings" (the 24h zero-result rule then flags it).
"""

from __future__ import annotations

import httpx

from tracker.fetchers.base import (
    FetchError,
    get_json,
    mentions_remote,
    parse_iso_date,
    register,
)
from tracker.models import AtsType, Company, RawPosting

API = "https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
PAGE_SIZE = 100
MAX_PAGES = 10


def normalize(company: Company, content: list[object]) -> list[RawPosting]:
    company_id = company.ats_config["company_id"]
    postings = []
    for job in content:
        if not isinstance(job, dict) or not job.get("id") or not job.get("name"):
            raise FetchError("smartrecruiters: posting without id or name")
        location = job.get("location") if isinstance(job.get("location"), dict) else {}
        full = location.get("fullLocation")
        locations = [full] if full else []
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="smartrecruiters",
                external_id=str(job["id"]),
                title=str(job["name"]).strip(),
                locations=locations,
                is_remote=bool(location.get("remote")) or mentions_remote(*locations),
                url=f"https://jobs.smartrecruiters.com/{company_id}/{job['id']}",
                date_posted=parse_iso_date(job.get("releasedDate")),
            )
        )
    return postings


@register(AtsType.smartrecruiters)
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    url = API.format(company_id=company.ats_config["company_id"])
    content: list[object] = []
    for _ in range(MAX_PAGES):
        params = {"q": "intern", "country": "in", "limit": PAGE_SIZE, "offset": len(content)}
        payload = await get_json(client, url, params=params)
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
            raise FetchError("smartrecruiters: response has no content list")
        total = payload.get("totalFound")
        if not isinstance(total, int):
            raise FetchError("smartrecruiters: response has no totalFound")
        if not payload["content"]:
            break
        content += payload["content"]
        if len(content) >= total:
            break
    return normalize(company, content)
