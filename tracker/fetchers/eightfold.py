"""Fetcher for Eightfold career sites (the "PCSX" search API).

`GET https://{host}/api/pcsx/search?domain={domain}&query=intern&location=India&start=N` returns
`data.positions[]` (a handful per page) and `data.count`, the total. The server already narrows
to India + "intern", so a board only needs a page or two.
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

MAX_PAGES = 20


def normalize(company: Company, host: str, positions: list[object]) -> list[RawPosting]:
    postings = []
    for job in positions:
        if not isinstance(job, dict) or job.get("id") is None or not job.get("name"):
            raise FetchError("eightfold: position without id or name")
        locations = [loc for loc in job.get("locations") or [] if isinstance(loc, str) and loc]
        path = job.get("positionUrl") or f"/careers/job/{job['id']}"
        posted = job.get("postedTs")
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="eightfold",
                external_id=str(job["id"]),
                title=str(job["name"]).strip(),
                locations=locations,
                is_remote=job.get("workLocationOption") == "remote" or mentions_remote(*locations),
                url=f"https://{host}{path}",
                date_posted=parse_epoch_ms_date(posted * 1000)
                if isinstance(posted, int | float) and not isinstance(posted, bool)
                else None,
            )
        )
    return postings


async def _page(client: httpx.AsyncClient, host: str, domain: str, start: int) -> dict:
    params = {
        "domain": domain,
        "query": "intern",
        "location": "India",
        "start": start,
        "sort_by": "timestamp",
    }
    payload = await get_json(client, f"https://{host}/api/pcsx/search", params=params)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("positions"), list):
        raise FetchError("eightfold: response has no data.positions list")
    if not isinstance(data.get("count"), int):
        raise FetchError("eightfold: response has no data.count")
    return data


@register(AtsType.eightfold)
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    host, domain = company.ats_config["host"], company.ats_config["domain"]
    positions: list[object] = []
    count = 0
    for _ in range(MAX_PAGES):
        data = await _page(client, host, domain, len(positions))
        count = data["count"]
        if not data["positions"]:
            break
        positions += data["positions"]
        if len(positions) >= count:
            break
    # `public_host`: the company's own careers domain for the posting links. Searching through it
    # is often rate-limited for GitHub's shared IPs, so the search uses the plain Eightfold host.
    return normalize(company, company.ats_config.get("public_host", host), positions)
