from datetime import date

import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher, oracle_hcm
from tracker.http import make_client
from tracker.models import Company

HOST, SITE = "acme.fa.oraclecloud.com", "CX_1"
API = f"https://{HOST}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
INDIA_FACET = [
    {"Id": 111, "Name": "United States", "TotalCount": 90},
    {"Id": 300000000289360, "Name": "India", "TotalCount": 7},
    {"Id": 222, "Name": "Pune, Maharashtra, India", "TotalCount": 3},
]


def req(n: int, **overrides) -> dict:
    data = {
        "Id": str(5000 + n),
        "Title": f"Software Engineer Intern {n}",
        "PostedDate": "2026-10-20",
        "PrimaryLocation": "Bengaluru, Karnataka, India",
        "PrimaryLocationCountry": "IN",
        "WorkplaceTypeCode": None,
        "secondaryLocations": [{"Name": "Pune, Maharashtra, India"}],
    }
    data.update(overrides)
    return data


def item(reqs: list[dict] | None = None, total: int | None = None, facet: list | None = None):
    body = {"TotalJobsCount": len(reqs or []) if total is None else total}
    if reqs is not None:
        body["requisitionList"] = reqs
    if facet is not None:
        body["locationsFacet"] = facet
    return {"items": [body]}


def company() -> Company:
    return Company(
        name="Acme",
        slug="acme",
        tier=1,
        ats="oracle_hcm",
        ats_config={"host": HOST, "site": SITE},
        enabled=True,
    )


async def run_fetch():
    async with make_client(delay=0, backoff=0) as client:
        return await oracle_hcm.fetch(company(), client)


def finders(route) -> list[str]:
    return [call.request.url.params["finder"] for call in route.calls]


def test_registered_for_oracle_hcm():
    assert get_fetcher(company()) is oracle_hcm.fetch


def test_find_india_location_id():
    assert (
        oracle_hcm.find_india_location_id(item(facet=INDIA_FACET)["items"][0]) == "300000000289360"
    )
    assert (
        oracle_hcm.find_india_location_id({"locationsFacet": [{"Id": 1, "Name": "Pune"}]}) is None
    )
    assert oracle_hcm.find_india_location_id({}) is None


async def test_india_facet_is_discovered_then_selected():
    with respx.mock:
        route = respx.get(API).mock(
            side_effect=[
                respx.MockResponse(200, json=item([], total=99, facet=INDIA_FACET)),
                respx.MockResponse(200, json=item([req(1), req(2)])),
            ]
        )
        postings = await run_fetch()
    discover, search = finders(route)
    assert "facetsList=LOCATIONS" in discover and "selectedLocationsFacet" not in discover
    assert "selectedLocationsFacet=300000000289360" in search
    assert 'keyword="intern"' in search and f"siteNumber={SITE}" in search
    assert route.calls.last.request.url.params["expand"] == "requisitionList.secondaryLocations"
    p = postings[0]
    assert p.source == "oracle_hcm" and p.external_id == "5001"
    assert p.title == "Software Engineer Intern 1"
    assert p.locations == ["Bengaluru, Karnataka, India", "Pune, Maharashtra, India"]
    assert p.date_posted == date(2026, 10, 20) and not p.is_remote
    assert p.url == f"https://{HOST}/hcmUI/CandidateExperience/en/sites/{SITE}/job/5001"


async def test_pages_by_offset_using_total():
    first = [req(i) for i in range(1, 51)]
    second = [req(i) for i in range(51, 56)]
    with respx.mock:
        route = respx.get(API).mock(
            side_effect=[
                respx.MockResponse(200, json=item([], total=55, facet=INDIA_FACET)),
                respx.MockResponse(200, json=item(first, total=55)),
                respx.MockResponse(200, json=item(second, total=55)),
            ]
        )
        postings = await run_fetch()
    assert len(postings) == 55
    assert "offset=0" in finders(route)[1] and "offset=50" in finders(route)[2]


async def test_without_india_facet_pages_everything_and_selects_nothing():
    with respx.mock:
        route = respx.get(API).respond(
            200, json=item([req(1)], total=1, facet=[{"Id": 1, "Name": "United States"}])
        )
        postings = await run_fetch()
    assert [p.external_id for p in postings] == ["5001"]
    assert all("selectedLocationsFacet" not in f for f in finders(route))
    assert route.call_count == 1  # the discovery query already returned the only page


async def test_without_india_facet_and_too_many_matches_fails_loudly():
    with respx.mock:
        respx.get(API).respond(200, json=item([req(1)], total=5000, facet=[]))
        with pytest.raises(FetchError, match="no India location facet"):
            await run_fetch()


async def test_remote_workplace_and_missing_optional_fields():
    odd = req(1, WorkplaceTypeCode="ORA_REMOTE", PostedDate=None, secondaryLocations=None)
    with respx.mock:
        respx.get(API).respond(200, json=item([odd], total=1, facet=[]))
        [p] = await run_fetch()
    assert p.is_remote and p.date_posted is None
    assert p.locations == ["Bengaluru, Karnataka, India"]


@pytest.mark.parametrize(
    "payload",
    [
        {"items": []},
        {"error": "x"},
        {"items": [{"TotalJobsCount": "many"}]},
        {"items": [{"TotalJobsCount": 1, "requisitionList": [{"Title": "No id"}]}]},
    ],
)
async def test_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run_fetch()


async def test_http_error_raises():
    with respx.mock:
        respx.get(API).respond(403)
        with pytest.raises(FetchError, match="403"):
            await run_fetch()
