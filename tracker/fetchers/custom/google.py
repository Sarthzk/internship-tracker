"""Google: the results page embeds its data in an `AF_initDataCallback` block (`ds:1`), laid out as
`[jobs | null, null, total, page_size]`. Each job is a positional list; only the fields below are
read. `q=intern&location=India` is filtered server-side (a handful of roles). Positional data is
fragile, so any shape we do not recognise raises instead of returning an empty list."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime

import httpx

from tracker.fetchers.base import FetchError, mentions_remote, register_custom
from tracker.models import Company, RawPosting

SEARCH = "https://www.google.com/about/careers/applications/jobs/results/"
MAX_PAGES = 10

_BLOCK = re.compile(
    r"AF_initDataCallback\(\{key: 'ds:1', hash: '[^']*', data:(.*?), sideChannel: \{\}\}\);",
    re.DOTALL,
)

# Positions inside one job record.
ID, TITLE, LOCATIONS, CREATED = 0, 1, 9, 12


def extract_block(html: str) -> tuple[list[object], int, int]:
    """(jobs on this page, total matches, page size) from a results page."""
    match = _BLOCK.search(html)
    if not match:
        raise FetchError("google: results page has no data block")
    try:
        data = json.loads(match.group(1))
    except ValueError as exc:
        raise FetchError("google: data block is not valid JSON") from exc
    if not (
        isinstance(data, list)
        and len(data) >= 4
        and (data[0] is None or isinstance(data[0], list))
        and isinstance(data[2], int)
        and isinstance(data[3], int)
        and data[3] > 0
    ):
        raise FetchError("google: data block has an unexpected layout")
    return data[0] or [], data[2], data[3]


def _created(value: object) -> date | None:
    if isinstance(value, list) and value and isinstance(value[0], int):
        return datetime.fromtimestamp(value[0], UTC).date()
    return None


def normalize(company: Company, jobs: list[object]) -> list[RawPosting]:
    postings = []
    for job in jobs:
        if (
            not isinstance(job, list)
            or len(job) <= CREATED
            or not isinstance(job[ID], str)
            or not isinstance(job[TITLE], str)
            or not job[TITLE]
        ):
            raise FetchError("google: job record has an unexpected layout")
        raw_locations = job[LOCATIONS] if isinstance(job[LOCATIONS], list) else []
        locations = [
            loc[0]
            for loc in raw_locations
            if isinstance(loc, list) and loc and isinstance(loc[0], str)
        ]
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=job[ID],
                title=job[TITLE].strip(),
                locations=locations,
                is_remote=mentions_remote(*locations),
                url=f"{SEARCH}{job[ID]}",
                date_posted=_created(job[CREATED]),
            )
        )
    return postings


@register_custom("google")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    jobs: list[object] = []
    total = 0
    for page in range(1, MAX_PAGES + 1):
        response = await client.get(
            SEARCH, params={"q": "intern", "location": "India", "page": page}
        )
        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code} from {response.url.host}")
        found, total, _size = extract_block(response.text)
        jobs += found
        if len(jobs) >= total or not found:
            break
    else:
        raise FetchError(f"google: more than {MAX_PAGES} pages of matches")
    if len(jobs) < total:
        raise FetchError(f"google: got {len(jobs)} of {total} jobs")
    return normalize(company, jobs)
