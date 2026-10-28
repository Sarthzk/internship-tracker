"""Quadeye: a small JSON feed of every opening (about 25, from Zoho Recruit) served by its own
website. No server-side filtering, so India and "intern" are picked out by the filters later."""

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

API = "https://www.quadeye.com/api/zoho-recruit/job-openings"
POSTING_URL = "https://quadeye.zohorecruit.in/jobs/Careers"


def _place(job: dict) -> str:
    parts = [str(job.get(key) or "") for key in ("City", "State", "Country")]
    return ", ".join(p for p in parts if p and p != "None")


def normalize(company: Company, jobs: list[object]) -> list[RawPosting]:
    postings = []
    for job in jobs:
        if not isinstance(job, dict) or not job.get("id") or not job.get("Posting_Title"):
            raise FetchError("quadeye: opening without id or title")
        if str(job.get("Publish")).lower() == "false":
            continue
        place = _place(job)
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=str(job["id"]),
                title=str(job["Posting_Title"]).strip(),
                locations=[place] if place else [],
                is_remote=mentions_remote(place),
                url=f"{POSTING_URL}/{job['id']}",
                date_posted=parse_iso_date(job.get("Date_Opened")),
            )
        )
    return postings


@register_custom("quadeye")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    payload = await get_json(client, API)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise FetchError("quadeye: response has no data list")
    return normalize(company, payload["data"])
