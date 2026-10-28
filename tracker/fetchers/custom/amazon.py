"""Amazon (amazon.jobs): `GET /en/search.json`, already narrowed to "intern" in India."""

from __future__ import annotations

import re
from datetime import date, datetime

import httpx

from tracker.fetchers.base import FetchError, get_json, mentions_remote, register_custom
from tracker.models import Company, RawPosting

API = "https://www.amazon.jobs/en/search.json"
PAGE_SIZE = 100
MAX_PAGES = 10
_COUNTRY = re.compile(r"\bIND$")


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%B %d, %Y").date()
    except ValueError:
        return None


def normalize(company: Company, jobs: list[object]) -> list[RawPosting]:
    postings = []
    for job in jobs:
        external_id = job.get("id_icims") or job.get("id") if isinstance(job, dict) else None
        if not external_id or not job.get("title") or not job.get("job_path"):
            raise FetchError("amazon: job without id, title or job_path")
        # "Bengaluru, Karnataka, IND" -> "Bengaluru, Karnataka, India" so the India filter matches.
        where = _COUNTRY.sub(
            "India", str(job.get("normalized_location") or job.get("location") or "")
        )
        locations = [where] if where else []
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=str(external_id),
                title=str(job["title"]).strip(),
                locations=locations,
                is_remote=mentions_remote(*locations),
                url=f"https://www.amazon.jobs{job['job_path']}",
                date_posted=_parse_date(job.get("posted_date")),
                description=job.get("description"),
            )
        )
    return postings


@register_custom("amazon")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    jobs: list[object] = []
    for _ in range(MAX_PAGES):
        params = {
            "base_query": "intern",
            "loc_query": "India",
            "country": "IND",
            "result_limit": PAGE_SIZE,
            "offset": len(jobs),
        }
        payload = await get_json(client, API, params=params)
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise FetchError("amazon: response has no jobs list")
        if not isinstance(payload.get("hits"), int):
            raise FetchError("amazon: response has no hits count")
        if not payload["jobs"]:
            break
        jobs += payload["jobs"]
        if len(jobs) >= payload["hits"]:
            break
    return normalize(company, jobs)
