"""Fetcher for Oracle HCM "Candidate Experience" career sites.

`GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions` with a
`finder=findReqs;siteNumber=...` query. We search for "intern" and, when the site's location facet
lists an exact "India" value, select it so only Indian postings come back. Sites that list only
their top few locations in the facet (so India may be missing) are paged in full instead, up to a
cap; beyond that the fetch fails loudly rather than silently missing postings.
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

PAGE_SIZE = 50
MAX_PAGES = 20
KEYWORD = "intern"
API = "https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
JOB_URL = "https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{id}"


async def _query(
    client: httpx.AsyncClient, company: Company, finder_extra: str, offset: int
) -> dict:
    cfg = company.ats_config
    finder = (
        f'findReqs;siteNumber={cfg["site"]},{finder_extra}keyword="{KEYWORD}",'
        f"limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC"
    )
    params = {
        "onlyData": "true",
        "expand": "requisitionList.secondaryLocations",
        "finder": finder,
    }
    payload = await get_json(client, API.format(host=cfg["host"]), params=params)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise FetchError("oracle_hcm: response has no items")
    item = items[0]
    if not isinstance(item.get("TotalJobsCount"), int):
        raise FetchError("oracle_hcm: response has no TotalJobsCount")
    return item


def find_india_location_id(item: dict) -> str | None:
    facet = item.get("locationsFacet")
    if not isinstance(facet, list):
        return None
    for value in facet:
        if (
            isinstance(value, dict)
            and str(value.get("Name", "")).strip().lower() == "india"
            and value.get("Id") is not None
        ):
            return str(value["Id"])
    return None


def normalize(company: Company, requisitions: list[object]) -> list[RawPosting]:
    host, site = company.ats_config["host"], company.ats_config["site"]
    postings = []
    for job in requisitions:
        if not isinstance(job, dict) or job.get("Id") is None or not job.get("Title"):
            raise FetchError("oracle_hcm: requisition without Id or Title")
        locations = [job["PrimaryLocation"]] if job.get("PrimaryLocation") else []
        for extra in job.get("secondaryLocations") or []:
            name = extra.get("Name") if isinstance(extra, dict) else None
            if name and name not in locations:
                locations.append(name)
        workplace = str(job.get("WorkplaceTypeCode") or "").lower()
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="oracle_hcm",
                external_id=str(job["Id"]),
                title=str(job["Title"]).strip(),
                locations=locations,
                is_remote="remote" in workplace or mentions_remote(*locations),
                url=JOB_URL.format(host=host, site=site, id=job["Id"]),
                date_posted=parse_iso_date(job.get("PostedDate")),
            )
        )
    return postings


@register(AtsType.oracle_hcm)
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    first = await _query(client, company, "facetsList=LOCATIONS,", 0)
    india = find_india_location_id(first)
    extra = f"selectedLocationsFacet={india}," if india else ""
    if india:
        first = await _query(client, company, extra, 0)
    total = first["TotalJobsCount"]
    if not india and total > MAX_PAGES * PAGE_SIZE:
        raise FetchError(f"oracle_hcm: {total} matches and no India location facet to narrow them")

    requisitions: list[object] = list(first.get("requisitionList") or [])
    offset = PAGE_SIZE
    while len(requisitions) < total and offset < MAX_PAGES * PAGE_SIZE:
        more = (await _query(client, company, extra, offset)).get("requisitionList") or []
        if not more:
            break
        requisitions += more
        offset += PAGE_SIZE
    return normalize(company, requisitions)
