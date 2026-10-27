"""Fetcher for greenhouse job boards.

`GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs` returns every job on the board.
Descriptions are not requested (`content=true` makes the payload many times larger); they are
only needed for enrichment, which is a later, optional phase.
"""

from __future__ import annotations

import httpx

from tracker.fetchers.base import FetchError, get_json, mentions_remote, parse_iso_date, register
from tracker.models import AtsType, Company, RawPosting

API = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"


def normalize(company: Company, payload: object) -> list[RawPosting]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise FetchError("greenhouse: response has no 'jobs' list")
    postings = []
    for job in payload["jobs"]:
        location = (job.get("location") or {}).get("name") or ""
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="greenhouse",
                external_id=str(job["id"]),
                title=(job.get("title") or "").strip(),
                locations=[location] if location else [],
                is_remote=mentions_remote(location),
                url=job["absolute_url"],
                date_posted=parse_iso_date(job.get("first_published")),
            )
        )
    return postings


@register(AtsType.greenhouse)
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    url = API.format(board_token=company.ats_config["board_token"])
    return normalize(company, await get_json(client, url))
