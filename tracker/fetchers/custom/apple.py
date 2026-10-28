"""Apple: the search page embeds its results as JSON (`window.__staticRouterHydrationData`), 20
roles per page. `location=india-INDC&search=intern` narrows the list to ~100 roles (the keyword
also matches descriptions), so the title filter later keeps only real internships. If the layout
changes the fetch fails instead of returning an empty list."""

from __future__ import annotations

import json
import re
from datetime import date

import httpx

from tracker.fetchers.base import FetchError, mentions_remote, parse_iso_date, register_custom
from tracker.models import Company, RawPosting

SEARCH = "https://jobs.apple.com/en-in/search"
DETAIL = "https://jobs.apple.com/en-in/details"
PAGE_SIZE = 20
MAX_PAGES = 10

_HYDRATION = re.compile(
    r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\("(.*?)"\);', re.DOTALL
)


def extract_search(html: str) -> dict:
    """The `search` loader data (searchResults, totalRecords) embedded in a search page."""
    match = _HYDRATION.search(html)
    if not match:
        raise FetchError("apple: search page has no embedded data")
    try:
        # The payload is a JavaScript string literal holding JSON; decode it twice.
        data = json.loads(json.loads(f'"{match.group(1)}"'))
        search = data["loaderData"]["search"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FetchError("apple: embedded data has an unexpected shape") from exc
    if not isinstance(search, dict) or not isinstance(search.get("searchResults"), list):
        raise FetchError("apple: embedded data has no searchResults")
    if not isinstance(search.get("totalRecords"), int):
        raise FetchError("apple: embedded data has no totalRecords")
    return search


def _location(loc: object) -> str:
    if not isinstance(loc, dict):
        return ""
    name, country = str(loc.get("name") or ""), str(loc.get("countryName") or "")
    return f"{name}, {country}" if country and country not in name else name


def normalize(company: Company, results: list[object]) -> list[RawPosting]:
    postings = []
    for job in results:
        if not isinstance(job, dict) or not job.get("positionId") or not job.get("postingTitle"):
            raise FetchError("apple: role without positionId or title")
        locations = [
            text for text in (_location(loc) for loc in job.get("locations") or []) if text
        ]
        team = job.get("team") if isinstance(job.get("team"), dict) else {}
        slug = job.get("transformedPostingTitle") or "role"
        url = f"{DETAIL}/{job['positionId']}/{slug}"
        if team.get("teamCode"):
            url += f"?team={team['teamCode']}"
        posted: date | None = parse_iso_date(job.get("postDateInGMT"))
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=str(job["positionId"]),
                title=str(job["postingTitle"]).strip(),
                locations=locations,
                is_remote=mentions_remote(*locations),
                url=url,
                date_posted=posted,
            )
        )
    return postings


@register_custom("apple")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    results: list[object] = []
    total = 0
    for page in range(1, MAX_PAGES + 1):
        response = await client.get(
            SEARCH, params={"location": "india-INDC", "search": "intern", "page": page}
        )
        if response.status_code != 200:
            raise FetchError(f"HTTP {response.status_code} from {response.url.host}")
        search = extract_search(response.text)
        total = search["totalRecords"]
        results += search["searchResults"]
        if len(results) >= total or not search["searchResults"]:
            break
    else:
        raise FetchError(f"apple: more than {MAX_PAGES * PAGE_SIZE} matches")
    if len(results) < total:
        raise FetchError(f"apple: got {len(results)} of {total} roles")
    return normalize(company, results)
