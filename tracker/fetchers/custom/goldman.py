"""Goldman Sachs (higher.gs.com): GraphQL `roleSearch` over early-career roles.

The schema is undocumented and can change without notice, so any GraphQL error or unexpected
shape raises `FetchError` (the health alert then tells the owner) instead of returning nothing.
"""

from __future__ import annotations

import httpx

from tracker.fetchers.base import FetchError, mentions_remote, post_json, register_custom
from tracker.models import Company, RawPosting

API = "https://api-higher.gs.com/gateway/api/v1/graphql"
PAGE_SIZE = 100
MAX_PAGES = 10
QUERY = """
query GetRoles($searchQueryInput: RoleSearchQueryInput!) {
  roleSearch(searchQueryInput: $searchQueryInput) {
    totalCount
    items { roleId jobTitle locations { city state country } }
  }
}
"""


def _place(location: object) -> str | None:
    if not isinstance(location, dict):
        return None
    parts = [location.get("city"), location.get("state"), location.get("country")]
    text = ", ".join(str(p) for p in parts if p)
    return text or None


def normalize(company: Company, items: list[object]) -> list[RawPosting]:
    postings = []
    for item in items:
        if not isinstance(item, dict) or not item.get("roleId") or not item.get("jobTitle"):
            raise FetchError("goldman: role without roleId or jobTitle")
        locations = [p for p in (_place(loc) for loc in item.get("locations") or []) if p]
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=str(item["roleId"]),
                title=str(item["jobTitle"]).strip(),
                locations=locations,
                is_remote=mentions_remote(*locations),
                url=f"https://higher.gs.com/roles/{item['roleId']}",
            )
        )
    return postings


@register_custom("goldman-sachs")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    items: list[object] = []
    for page_number in range(MAX_PAGES):
        variables = {
            "searchQueryInput": {
                "page": {"pageSize": PAGE_SIZE, "pageNumber": page_number},
                "sort": {"sortStrategy": "RELEVANCE", "sortOrder": "DESC"},
                "experiences": ["EARLY_CAREER"],
                "filters": [],
                "searchTerm": "",
            }
        }
        payload = await post_json(client, API, json={"query": QUERY, "variables": variables})
        if not isinstance(payload, dict):
            raise FetchError("goldman: response is not an object")
        if payload.get("errors"):
            raise FetchError("goldman: GraphQL errors (schema may have changed)")
        data = payload.get("data")
        search = data.get("roleSearch") if isinstance(data, dict) else None
        if not isinstance(search, dict) or not isinstance(search.get("items"), list):
            raise FetchError("goldman: response has no roleSearch.items")
        total = search.get("totalCount")
        if not isinstance(total, int):
            raise FetchError("goldman: response has no totalCount")
        if not search["items"]:
            break
        items += search["items"]
        if len(items) >= total:
            break
    return normalize(company, items)
