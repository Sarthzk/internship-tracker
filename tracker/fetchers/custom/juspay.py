"""Juspay: one JSON feed of every opening (~95). Internships are marked by `job_type: Intern`
rather than by the title, so "Intern" is appended to such titles for the internship filter."""

from __future__ import annotations

import httpx

from tracker.fetchers.base import FetchError, get_json, mentions_remote, register_custom
from tracker.models import Company, RawPosting

API = "https://joinus.juspay.in/api/careerJobOpening"
APPLY_URL = "https://joinus.juspay.in/"


def _open(job: dict) -> bool:
    return str(job.get("opening_status")).lower() != "false"


def normalize(company: Company, jobs: list[object]) -> list[RawPosting]:
    postings = []
    for job in jobs:
        if not isinstance(job, dict) or not job.get("job_id") or not job.get("job_title"):
            raise FetchError("juspay: opening without job_id or job_title")
        if not _open(job):
            continue
        title = str(job["job_title"]).strip()
        if str(job.get("job_type")).lower() == "intern" and "intern" not in title.lower():
            title = f"{title} Intern"
        place = str(job.get("job_location") or "").strip()
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=str(job["job_id"]),
                title=title,
                locations=[place] if place else [],
                is_remote=mentions_remote(place),
                url=f"{APPLY_URL}?jobId={job['job_id']}",
            )
        )
    return postings


@register_custom("juspay")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    payload = await get_json(client, API, params={"limit": 1000})
    if not isinstance(payload, dict) or not isinstance(payload.get("allJobs"), list):
        raise FetchError("juspay: response has no allJobs list")
    return normalize(company, payload["allJobs"])
