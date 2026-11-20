"""Amazon (amazon.jobs): `GET /en/search.json`, already narrowed to "intern" in India.

Amazon's India student internships (for example "SDE I Intern, Amazon University Talent
Acquisition") are public pages but never appear in that search, whatever the query. They are
listed by hand in `ats_config.pinned_job_ids`; each pinned job's page is read directly.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime

import httpx

from tracker.fetchers.base import (
    BLOCKED_MESSAGE,
    BlockedError,
    FetchError,
    get_json,
    mentions_remote,
    register_custom,
)
from tracker.http import is_challenge
from tracker.models import Company, RawPosting

API = "https://www.amazon.jobs/en/search.json"
PAGE_SIZE = 100
MAX_PAGES = 10
JOB_PAGE = "https://www.amazon.jobs/en/jobs/{job_id}"
_COUNTRY = re.compile(r"\bIND$")
_OG_TITLE = re.compile(r'<meta property="og:title" content="([^"]*)"')
_LOCATION_LIST = re.compile(
    r'<div class="association location-icon">.*?<ul class="[^"]*">(.*?)</ul>', re.DOTALL
)
_LIST_ITEM = re.compile(r"<li>(.*?)</li>", re.DOTALL)


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


def parse_job_page(company: Company, job_id: str, page: str) -> RawPosting | None:
    """One pinned job page -> a posting, or None when the job is no longer open for applications."""
    title = _OG_TITLE.search(page)
    block = _LOCATION_LIST.search(page)
    if not title or not block:
        raise FetchError(f"amazon: job page {job_id} has no title or location list")
    if 'id="apply-button"' not in page:
        return None
    # "IND, KA, Bengaluru" -> "Bengaluru, India": the last part is the city.
    cities = [
        html.unescape(item).split(",")[-1].strip() for item in _LIST_ITEM.findall(block.group(1))
    ]
    locations = list(dict.fromkeys(f"{city}, India" for city in cities if city))
    return RawPosting(
        company_slug=company.slug,
        source="custom",
        external_id=job_id,
        title=html.unescape(title.group(1)).strip(),
        locations=locations,
        is_remote=False,
        url=JOB_PAGE.format(job_id=job_id),
    )


async def fetch_pinned(
    company: Company, client: httpx.AsyncClient, job_ids: list[str]
) -> list[RawPosting]:
    postings = []
    for job_id in job_ids:
        response = await client.get(JOB_PAGE.format(job_id=job_id))
        if is_challenge(response):
            raise BlockedError(BLOCKED_MESSAGE)
        if response.status_code == 404:
            continue  # the job was taken down: it simply is not listed any more
        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code} from {response.url.host}")
        posting = parse_job_page(company, job_id, response.text)
        if posting:
            postings.append(posting)
    return postings


@register_custom("amazon")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    found = await fetch_search(company, client)
    seen = {p.external_id for p in found}
    pinned = [str(i) for i in company.ats_config.get("pinned_job_ids", []) if str(i) not in seen]
    return found + await fetch_pinned(company, client, pinned)


async def fetch_search(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
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
