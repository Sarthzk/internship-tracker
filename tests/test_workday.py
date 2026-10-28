import json

import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher, workday
from tracker.http import make_client
from tracker.models import Company

HOST, TENANT, SITE = "acme.wd1.myworkdayjobs.com", "acme", "Careers"
BASE = f"https://{HOST}/wday/cxs/{TENANT}/{SITE}"
SEARCH = f"{BASE}/jobs"

COUNTRY_FACETS = [
    {
        "facetParameter": "locationMainGroup",
        "values": [
            {
                "facetParameter": "locationCountry",
                "descriptor": "Locations",
                "values": [
                    {"descriptor": "India", "id": "IN-ID", "count": 3},
                    {"descriptor": "Germany", "id": "DE-ID", "count": 1},
                ],
            }
        ],
    }
]
SITE_FACETS = [
    {
        "facetParameter": "locationMainGroup",
        "values": [
            {
                "facetParameter": "locations",
                "descriptor": "Sites",
                "values": [
                    {"descriptor": "India, Bangalore", "id": "BLR", "count": 2},
                    {"descriptor": "Mumbai Remote", "id": "BOM", "count": 1},
                    {"descriptor": "Indianapolis, Indiana", "id": "IND", "count": 1},
                ],
            }
        ],
    }
]
NO_INDIA_FACETS = [
    {
        "facetParameter": "locationMainGroup",
        "values": [
            {
                "facetParameter": "locations",
                "values": [{"descriptor": "Germany, Munich", "id": "MUC", "count": 1}],
            }
        ],
    }
]


def job(n: int, title: str = "Software Engineer Intern", where: str = "India, Bangalore") -> dict:
    return {
        "title": f"{title} {n}",
        "externalPath": f"/job/India-Bangalore/{title.replace(' ', '-')}-{n}_JR{n}",
        "locationsText": where,
        "postedOn": "Posted 3 Days Ago",
        "bulletFields": [f"JR{n}"],
    }


def page(jobs: list[dict], total: int | None = None, facets: list | None = None) -> dict:
    return {
        "total": len(jobs) if total is None else total,
        "jobPostings": jobs,
        "facets": facets or [],
    }


def company() -> Company:
    return Company(
        name="Acme",
        slug="acme",
        tier=1,
        ats="workday",
        ats_config={"host": HOST, "tenant": TENANT, "site": SITE},
        enabled=True,
    )


async def run_fetch():
    async with make_client(delay=0, backoff=0) as client:
        return await workday.fetch(company(), client)


def bodies(route) -> list[dict]:
    return [json.loads(call.request.content) for call in route.calls]


def test_registered_for_workday():
    assert get_fetcher(company()) is workday.fetch


def test_find_india_facets_prefers_exact_country():
    assert workday.find_india_facets(COUNTRY_FACETS) == {"locationCountry": ["IN-ID"]}


def test_find_india_facets_falls_back_to_indian_sites():
    # "Indianapolis, Indiana" must not be mistaken for India.
    assert workday.find_india_facets(SITE_FACETS) == {"locations": ["BLR", "BOM"]}


def test_find_india_facets_none_when_absent():
    assert workday.find_india_facets(NO_INDIA_FACETS) == {}
    assert workday.find_india_facets([]) == {}
    assert workday.find_india_facets("garbage") == {}


def test_external_id_is_the_requisition_id():
    assert workday._external_id("/job/Pune/Some-Title_JR123") == "JR123"
    assert workday._external_id("/job/Pune/NoUnderscore") == "/job/Pune/NoUnderscore"


async def test_country_facet_is_applied_and_postings_normalized():
    with respx.mock:
        route = respx.post(SEARCH).mock(
            side_effect=[
                respx.MockResponse(200, json=page([job(9)], total=500, facets=COUNTRY_FACETS)),
                respx.MockResponse(200, json=page([job(1), job(2)], facets=COUNTRY_FACETS)),
            ]
        )
        postings = await run_fetch()
    first, second = bodies(route)
    assert first["appliedFacets"] == {} and first["searchText"] == "intern"
    assert second["appliedFacets"] == {"locationCountry": ["IN-ID"]}
    assert [p.external_id for p in postings] == ["JR1", "JR2"]
    p = postings[0]
    assert p.source == "workday" and p.company_slug == "acme"
    assert p.title == "Software Engineer Intern 1" and p.locations == ["India, Bangalore"]
    assert p.url == f"https://{HOST}/{SITE}/job/India-Bangalore/Software-Engineer-Intern-1_JR1"
    assert p.date_posted is None and not p.is_remote


async def test_pages_by_offset_even_though_only_page_one_has_total():
    first = [job(i) for i in range(1, 21)]
    second = [job(i) for i in range(21, 26)]
    with respx.mock:
        route = respx.post(SEARCH).mock(
            side_effect=[
                respx.MockResponse(200, json=page(first, total=25, facets=COUNTRY_FACETS)),
                respx.MockResponse(200, json=page(first, total=25)),
                respx.MockResponse(200, json=page(second, total=0)),
            ]
        )
        postings = await run_fetch()
    assert len(postings) == 25
    assert [b["offset"] for b in bodies(route)] == [0, 0, 20]
    assert all(b["limit"] == 20 for b in bodies(route))


async def test_multi_location_posting_gets_one_detail_request():
    detail = {
        "jobPostingInfo": {
            "location": "Germany, Munich",
            "additionalLocations": ["India, Bangalore", "India, Pune"],
            "startDate": "2026-10-13",
            "jobDescription": "long text that must not be kept",
        }
    }
    multi = job(7, where="2 Locations")
    with respx.mock:
        respx.post(SEARCH).mock(
            side_effect=[
                respx.MockResponse(200, json=page([job(9)], facets=SITE_FACETS)),
                respx.MockResponse(200, json=page([multi, job(8)], facets=SITE_FACETS)),
            ]
        )
        detail_route = respx.get(f"{BASE}{multi['externalPath']}").respond(200, json=detail)
        postings = await run_fetch()
    assert detail_route.call_count == 1
    by_id = {p.external_id: p for p in postings}
    assert by_id["JR7"].locations == ["Germany, Munich", "India, Bangalore", "India, Pune"]
    assert str(by_id["JR7"].date_posted) == "2026-10-13"
    assert by_id["JR8"].locations == ["India, Bangalore"]
    assert "description" not in by_id["JR7"].model_dump()


async def test_detail_failure_fails_the_fetch():
    multi = job(7, where="3 Locations")
    with respx.mock:
        respx.post(SEARCH).mock(
            side_effect=[
                respx.MockResponse(200, json=page([job(9)], facets=SITE_FACETS)),
                respx.MockResponse(200, json=page([multi], facets=SITE_FACETS)),
            ]
        )
        respx.get(f"{BASE}{multi['externalPath']}").respond(404)
        with pytest.raises(FetchError):
            await run_fetch()


async def test_board_listing_locations_without_india_has_no_postings():
    with respx.mock:
        route = respx.post(SEARCH).respond(200, json=page([job(1)], facets=NO_INDIA_FACETS))
        assert await run_fetch() == []
    assert route.call_count == 1


async def test_no_location_facet_and_too_many_matches_fails_loudly():
    with respx.mock:
        respx.post(SEARCH).respond(200, json=page([job(1)], total=5000))
        with pytest.raises(FetchError, match="no location facet"):
            await run_fetch()


async def test_no_location_facet_and_few_matches_is_fine():
    with respx.mock:
        respx.post(SEARCH).respond(200, json=page([job(1), job(2)]))
        assert len(await run_fetch()) == 2


async def test_unlinkable_postings_are_skipped_but_all_bad_fails():
    broken = {"title": "No path", "locationsText": "India"}
    with respx.mock:
        respx.post(SEARCH).respond(200, json=page([broken, job(1)]))
        assert [p.external_id for p in await run_fetch()] == ["JR1"]
    with respx.mock:
        respx.post(SEARCH).respond(200, json=page([broken]))
        with pytest.raises(FetchError):
            await run_fetch()


@pytest.mark.parametrize(
    "payload",
    [{"error": "x"}, {"jobPostings": "nope", "total": 1}, {"jobPostings": [], "total": "many"}],
)
async def test_unexpected_shape_raises(payload):
    with respx.mock:
        respx.post(SEARCH).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run_fetch()


async def test_http_error_raises():
    with respx.mock:
        respx.post(SEARCH).respond(403)
        with pytest.raises(FetchError, match="403"):
            await run_fetch()
