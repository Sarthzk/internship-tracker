"""Fetch the description text of one listing, for enrichment only.

The text is passed to the LLM in memory and never stored. Only sources whose
detail endpoint is known are supported; for the others (custom portals, Phenom) there is no
description and the listing is simply not enriched. Nothing here raises: a missing description
must never break a run.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

import httpx

from tracker.fetchers.base import get_json
from tracker.models import Company, Listing

log = logging.getLogger(__name__)

MAX_CHARS = 20_000

DescriptionFn = Callable[[Listing, Company, httpx.AsyncClient], Awaitable[str | None]]


def to_text(markup: object) -> str:
    """HTML (possibly escaped twice) to plain text."""
    if not isinstance(markup, str):
        return ""
    text = html.unescape(markup)
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html.unescape(text))
    return re.sub(r"\s+", " ", text).strip()[:MAX_CHARS]


async def _greenhouse(listing: Listing, company: Company, client: httpx.AsyncClient) -> str | None:
    token = company.ats_config["board_token"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{listing.external_id}"
    payload = await get_json(client, url)
    return to_text(payload.get("content")) if isinstance(payload, dict) else None


async def _workday(listing: Listing, company: Company, client: httpx.AsyncClient) -> str | None:
    cfg = company.ats_config
    # The posting URL ends in `/job/<location>/<slug>`; the same path on the JSON API is the detail.
    path = urlparse(listing.url).path
    marker = path.find("/job/")
    if marker < 0:
        return None
    url = f"https://{cfg['host']}/wday/cxs/{cfg['tenant']}/{cfg['site']}{path[marker:]}"
    payload = await get_json(client, url, headers={"Accept": "application/json"})
    info = payload.get("jobPostingInfo") if isinstance(payload, dict) else None
    return to_text(info.get("jobDescription")) if isinstance(info, dict) else None


async def _eightfold(listing: Listing, company: Company, client: httpx.AsyncClient) -> str | None:
    cfg = company.ats_config
    url = f"https://{cfg['host']}/api/apply/v2/jobs/{listing.external_id}"
    payload = await get_json(client, url, params={"domain": cfg["domain"]})
    return to_text(payload.get("job_description")) if isinstance(payload, dict) else None


async def _smartrecruiters(
    listing: Listing, company: Company, client: httpx.AsyncClient
) -> str | None:
    url = (
        f"https://api.smartrecruiters.com/v1/companies/{company.ats_config['company_id']}"
        f"/postings/{listing.external_id}"
    )
    payload = await get_json(client, url)
    ad = payload.get("jobAd") if isinstance(payload, dict) else None
    sections = ad.get("sections") if isinstance(ad, dict) else None
    if not isinstance(sections, dict):
        return None
    parts = [
        to_text(section.get("text"))
        for name, section in sections.items()
        if name != "companyDescription" and isinstance(section, dict)
    ]
    return " ".join(p for p in parts if p)[:MAX_CHARS]


async def _oracle(listing: Listing, company: Company, client: httpx.AsyncClient) -> str | None:
    cfg = company.ats_config
    url = f"https://{cfg['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
    finder = f'ById;Id="{listing.external_id}",siteNumber={cfg["site"]}'
    payload = await get_json(
        client, url, params={"expand": "all", "onlyData": "true", "finder": finder}
    )
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    item = items[0]
    keys = ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")
    return " ".join(to_text(item.get(key)) for key in keys if item.get(key))[:MAX_CHARS]


FETCHERS: dict[str, DescriptionFn] = {
    "greenhouse": _greenhouse,
    "workday": _workday,
    "eightfold": _eightfold,
    "smartrecruiters": _smartrecruiters,
    "oracle_hcm": _oracle,
}


def can_fetch(listing: Listing) -> bool:
    return listing.source in FETCHERS


async def fetch_description(
    listing: Listing, company: Company, client: httpx.AsyncClient
) -> str | None:
    """The plain-text description, or None when unsupported or unavailable."""
    fn = FETCHERS.get(listing.source)
    if fn is None:
        return None
    try:
        text = await fn(listing, company, client)
    except Exception as exc:  # noqa: BLE001 - a description is optional, never fail the run
        log.warning("no description for %s: %s", listing.id, type(exc).__name__)
        return None
    return text or None
