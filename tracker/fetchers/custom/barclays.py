"""Barclays: Radancy TalentBrew. The results endpoint returns JSON whose `results` field is an
HTML list. The keyword search ("intern") finds ~60 jobs worldwide and ignores `Location`, so it is
one request and India is picked out by the filters later. The count parsed from the HTML must
match the page's own total, so a changed layout fails loudly instead of looking like "no jobs"."""

from __future__ import annotations

import html
import re

import httpx

from tracker.fetchers.base import FetchError, get_json, mentions_remote, register_custom
from tracker.models import Company, RawPosting

HOST = "https://search.jobs.barclays"
API = f"{HOST}/search-jobs/results"
PAGE_SIZE = 100
MAX_PAGES = 5

_TOTAL = re.compile(r'data-total-job-results="(\d+)"')
_PAGES = re.compile(r'data-total-pages="(\d+)"')
_JOB = re.compile(
    r'<a href="([^"]+)"[^>]*data-job-id="(\d+)"[^>]*>(.*?)</a>\s*'
    r'<div class="job-location">(.*?)</div>',
    re.DOTALL,
)
_TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return html.unescape(_TAGS.sub("", fragment)).strip()


def _params(page: int) -> dict[str, str | int]:
    return {
        "ActiveFacetID": 0,
        "CurrentPage": page,
        "RecordsPerPage": PAGE_SIZE,
        "Distance": 50,
        "RadiusUnitType": 0,
        "Keywords": "intern",
        "Location": "",
        "ShowRadius": "False",
        "IsPagination": "False",
        "FacetType": 0,
        "SearchResultsModuleName": "Search Results",
        "SearchFiltersModuleName": "Search Filters",
        "SortCriteria": 0,
        "SortDirection": 0,
        "SearchType": 5,
        "ResultsType": 0,
    }


def parse_page(company: Company, results_html: str) -> tuple[list[RawPosting], int, int]:
    """(postings, total jobs, total pages) from one `results` HTML fragment."""
    total, pages = _TOTAL.search(results_html), _PAGES.search(results_html)
    if not total or not pages:
        raise FetchError("barclays: results page has no totals")
    postings = []
    for href, job_id, title, location in _JOB.findall(results_html):
        title, place = _text(title), _text(location)
        if not title:
            raise FetchError("barclays: job without a title")
        postings.append(
            RawPosting(
                company_slug=company.slug,
                source="custom",
                external_id=job_id,
                title=title,
                locations=[place] if place else [],
                is_remote=mentions_remote(place),
                url=f"{HOST}{href}",
            )
        )
    return postings, int(total.group(1)), int(pages.group(1))


@register_custom("barclays")
async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]:
    postings: list[RawPosting] = []
    total = 0
    for page in range(1, MAX_PAGES + 1):
        payload = await get_json(client, API, params=_params(page))
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), str):
            raise FetchError("barclays: response has no results HTML")
        found, total, pages = parse_page(company, payload["results"])
        postings += found
        if page >= pages:
            break
    else:
        raise FetchError(f"barclays: more than {MAX_PAGES} pages of matches")
    if len(postings) != total:
        raise FetchError(f"barclays: parsed {len(postings)} of {total} jobs")
    return postings
