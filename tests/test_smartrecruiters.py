from datetime import date

import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher, smartrecruiters
from tracker.http import make_client
from tracker.models import Company

API = "https://api.smartrecruiters.com/v1/companies/acme/postings"


def job(n: int, **overrides) -> dict:
    data = {
        "id": f"600000{n}",
        "name": f"Software Engineer Intern {n}",
        "releasedDate": "2026-10-27T10:09:35.629Z",
        "location": {
            "city": "Bengaluru",
            "country": "in",
            "remote": False,
            "fullLocation": "Bengaluru, KA, India",
        },
    }
    data.update(overrides)
    return data


def page(jobs: list[dict], total: int | None = None) -> dict:
    return {
        "offset": 0,
        "limit": 100,
        "totalFound": len(jobs) if total is None else total,
        "content": jobs,
    }


def company() -> Company:
    return Company(
        name="Acme",
        slug="acme",
        tier=2,
        ats="smartrecruiters",
        ats_config={"company_id": "acme"},
        enabled=True,
    )


async def run_fetch():
    async with make_client(delay=0, backoff=0) as client:
        return await smartrecruiters.fetch(company(), client)


def test_registered_for_smartrecruiters():
    assert get_fetcher(company()) is smartrecruiters.fetch


async def test_normalizes_and_asks_server_for_india_interns():
    with respx.mock:
        route = respx.get(API).respond(200, json=page([job(1)]))
        [p] = await run_fetch()
    params = route.calls.last.request.url.params
    assert params["q"] == "intern" and params["country"] == "in" and params["offset"] == "0"
    assert p.source == "smartrecruiters" and p.external_id == "6000001"
    assert p.title == "Software Engineer Intern 1" and p.locations == ["Bengaluru, KA, India"]
    assert p.url == "https://jobs.smartrecruiters.com/acme/6000001"
    assert p.date_posted == date(2026, 10, 27) and not p.is_remote


async def test_pages_with_offset_until_total_found():
    with respx.mock:
        route = respx.get(API).mock(
            side_effect=[
                respx.MockResponse(200, json=page([job(1), job(2)], total=3)),
                respx.MockResponse(200, json=page([job(3)], total=3)),
            ]
        )
        postings = await run_fetch()
    assert len(postings) == 3
    assert [c.request.url.params["offset"] for c in route.calls] == ["0", "2"]


async def test_empty_board_is_an_empty_list():
    with respx.mock:
        respx.get(API).respond(200, json=page([]))
        assert await run_fetch() == []


async def test_remote_flag_and_missing_location():
    remote = job(1, location={"remote": True, "fullLocation": "India"})
    nowhere = job(2, location=None)
    with respx.mock:
        respx.get(API).respond(200, json=page([remote, nowhere]))
        first, second = await run_fetch()
    assert first.is_remote and second.locations == []


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "x"},
        {"content": "nope", "totalFound": 1},
        {"content": [], "totalFound": "many"},
        {"content": [{"name": "No id"}], "totalFound": 1},
    ],
)
async def test_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run_fetch()


async def test_http_error_raises():
    with respx.mock:
        respx.get(API).respond(500)
        with pytest.raises(FetchError, match="500"):
            await run_fetch()
