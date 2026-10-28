"""Fetcher for Workday career sites (`*.myworkdayjobs.com`).

`POST https://{host}/wday/cxs/{tenant}/{site}/jobs` searches the board, 20 postings per page.
We search for "intern" and, when the site offers an "India" location facet, ask the server for
India only, so we never page through thousands of jobs. A posting with several locations only
says "2 Locations" in the list, so those (and only those) get one detail request for the real
locations and the start date.

The page limit is a safety net: if a board offers no location facet and has more matches than
we are willing to page through, the fetch fails loudly instead of silently missing postings.
"""

from __future__ import annotations

import re

import httpx

from tracker.fetchers.base import (
    FetchError,
    get_json,
    mentions_remote,
    parse_iso_date,
    post_json,
    register,
)
from tracker.filters import INDIA
from tracker.models import AtsType, Company, RawPosting

PAGE_SIZE = 20  # Workday rejects larger limits
MAX_PAGES = 25
SEARCH_TEXT = "intern"

_MULTI_LOCATION = re.compile(r"\d+ locations?", re.IGNORECASE)
_REQ_ID = re.compile(r"_([^_/]+)$")


def _as_dict(value: object, what: str) -> dict:
    if not isinstance(value, dict):
        raise FetchError(f"workday: {what} is not an object")
    return value


def _location_facets(facets: object) -> list[tuple[str, dict]]:
    """Every (facetParameter, value) pair under a facet group whose name starts with 'location'."""
    found: list[tuple[str, dict]] = []

    def walk(items: object, param: str | None) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("facetParameter") or param
            if isinstance(item.get("values"), list) and item["values"]:
                walk(item["values"], name)
            elif item.get("id") and param and param.lower().startswith("location"):
                found.append((param, item))

    walk(facets, None)
    return found


def find_india_facets(facets: object) -> dict[str, list[str]]:
    """Facet selections that narrow the search to India, as `appliedFacets` entries.

    Boards with a country facet have an exact "India" value. Others only list sites such as
    "India, Bangalore" or "Mumbai Remote", so every site that names an Indian place is selected
    (values of one facet are OR-ed)."""
    pairs = _location_facets(facets)
    for param, value in pairs:
        if str(value.get("descriptor", "")).strip().lower() == "india":
            return {param: [str(value["id"])]}
    selected: dict[str, list[str]] = {}
    for param, value in pairs:
        if INDIA.search(str(value.get("descriptor", ""))):
            ids = selected.setdefault(param, [])
            if str(value["id"]) not in ids:
                ids.append(str(value["id"]))
    return selected


def _external_id(path: str) -> str:
    """The requisition id after the last underscore, e.g. `.../Title_JR2027176` -> `JR2027176`.

    It survives retitling, unlike the rest of the path. Falls back to the whole path."""
    match = _REQ_ID.search(path)
    return match.group(1) if match else path


async def _search(client: httpx.AsyncClient, base: str, facets: dict, offset: int) -> dict:
    body = {
        "appliedFacets": facets,
        "limit": PAGE_SIZE,
        "offset": offset,
        "searchText": SEARCH_TEXT,
    }
    payload = _as_dict(await post_json(client, f"{base}/jobs", json=body), "search response")
    if not isinstance(payload.get("jobPostings"), list):
        raise FetchError("workday: search response has no jobPostings list")
    return payload


async def _detail(client: httpx.AsyncClient, base: str, path: str) -> dict:
    payload = _as_dict(await get_json(client, f"{base}{path}"), "detail response")
    return _as_dict(payload.get("jobPostingInfo"), "jobPostingInfo")


def _detail_locations(info: dict) -> list[str]:
    locations = [info["location"]] if info.get("location") else []
    extra = info.get("additionalLocations")
    if isinstance(extra, list):
        locations += [loc for loc in extra if isinstance(loc, str) and loc]
    return locations


async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    cfg = company.ats_config
    host, tenant, site = cfg["host"], cfg["tenant"], cfg["site"]
    base = f"https://{host}/wday/cxs/{tenant}/{site}"

    page = await _search(client, base, {}, 0)
    total = page.get("total")
    if not isinstance(total, int):
        raise FetchError("workday: search response has no total")
    facets = find_india_facets(page.get("facets"))
    if facets:
        page = await _search(client, base, facets, 0)
        total = page.get("total")
        if not isinstance(total, int):
            raise FetchError("workday: filtered search response has no total")
    elif _location_facets(page.get("facets")):
        # The board lists locations but India is not among them: no India matches at all.
        return []
    elif total > MAX_PAGES * PAGE_SIZE:
        raise FetchError(f"workday: {total} matches and no location facet to narrow them")

    # Only the first page reports `total`, so keep it and page by offset.
    jobs: list[dict] = list(page["jobPostings"])
    offset = PAGE_SIZE
    while len(jobs) < total and offset < MAX_PAGES * PAGE_SIZE:
        more = (await _search(client, base, facets, offset))["jobPostings"]
        if not more:
            break
        jobs += more
        offset += PAGE_SIZE

    postings = []
    skipped = 0
    for job in jobs:
        if not isinstance(job, dict) or not job.get("externalPath") or not job.get("title"):
            skipped += 1  # nothing to link to, so it cannot be published
            continue
        path = job["externalPath"]
        locations = [job["locationsText"]] if job.get("locationsText") else []
        date_posted = None
        if len(locations) == 1 and _MULTI_LOCATION.fullmatch(locations[0].strip()):
            info = await _detail(client, base, path)
            locations = _detail_locations(info) or locations
            date_posted = parse_iso_date(info.get("startDate"))
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="workday",
                external_id=_external_id(path),
                title=job["title"].strip(),
                locations=locations,
                is_remote=mentions_remote(*locations),
                url=f"https://{host}/{site}{path}",
                date_posted=date_posted,
            )
        )
    if jobs and not postings:
        raise FetchError(f"workday: none of {skipped} postings has a title and path")
    return postings


register(AtsType.workday)(fetch)
