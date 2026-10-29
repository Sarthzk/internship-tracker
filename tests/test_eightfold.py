from datetime import date

import pytest
import respx

from tracker.fetchers import FetchError, eightfold, get_fetcher
from tracker.http import make_client
from tracker.models import Company

HOST, DOMAIN = "careers.acme.com", "acme.com"
SEARCH = f"https://{HOST}/api/pcsx/search"


def position(n: int, **overrides) -> dict:
    data = {
        "id": 1000 + n,
        "name": f"Software Engineer Intern {n}",
        "locations": ["Bangalore, India", "Hyderabad, Telangāna, India"],
        "postedTs": 1788912000,  # 2026-09-09
        "positionUrl": f"/careers/job/{1000 + n}",
        "workLocationOption": "onsite",
    }
    data.update(overrides)
    return data


def body(positions: list[dict], count: int | None = None) -> dict:
    return {
        "status": 200,
        "data": {"positions": positions, "count": len(positions) if count is None else count},
    }


def company() -> Company:
    return Company(
        name="Acme",
        slug="acme",
        tier=1,
        ats="eightfold",
        ats_config={"host": HOST, "domain": DOMAIN},
        enabled=True,
    )


async def run_fetch():
    async with make_client(delay=0, backoff=0) as client:
        return await eightfold.fetch(company(), client)


def test_registered_for_eightfold():
    assert get_fetcher(company()) is eightfold.fetch


async def test_normalizes_and_asks_server_for_india_interns():
    with respx.mock:
        route = respx.get(SEARCH).respond(200, json=body([position(1)]))
        [p] = await run_fetch()
    params = route.calls.last.request.url.params
    assert params["domain"] == DOMAIN and params["query"] == "intern"
    assert params["location"] == "India" and params["start"] == "0"
    assert p.source == "eightfold" and p.external_id == "1001"
    assert p.title == "Software Engineer Intern 1"
    assert p.locations == ["Bangalore, India", "Hyderabad, Telangāna, India"]
    assert p.url == f"https://{HOST}/careers/job/1001"
    assert p.date_posted == date(2026, 9, 9) and not p.is_remote


async def test_pages_with_start_until_count_is_reached():
    with respx.mock:
        route = respx.get(SEARCH).mock(
            side_effect=[
                respx.MockResponse(200, json=body([position(1), position(2)], count=3)),
                respx.MockResponse(200, json=body([position(3)], count=3)),
            ]
        )
        postings = await run_fetch()
    assert [p.external_id for p in postings] == ["1001", "1002", "1003"]
    assert [c.request.url.params["start"] for c in route.calls] == ["0", "2"]


async def test_empty_result_is_an_empty_list():
    with respx.mock:
        respx.get(SEARCH).respond(200, json=body([]))
        assert await run_fetch() == []


async def test_remote_and_missing_fields():
    odd = position(1, workLocationOption="remote", postedTs=None, positionUrl=None)
    with respx.mock:
        respx.get(SEARCH).respond(200, json=body([odd]))
        [p] = await run_fetch()
    assert p.is_remote and p.date_posted is None
    assert p.url == f"https://{HOST}/careers/job/1001"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": 200},
        {"data": {"positions": "x", "count": 1}},
        {"data": {"positions": []}},
        {"data": {"positions": [{"name": "No id"}], "count": 1}},
    ],
)
async def test_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(SEARCH).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run_fetch()


async def test_plain_text_rate_limit_message_raises():
    with respx.mock:
        respx.get(SEARCH).respond(200, text="Please try again later")
        with pytest.raises(FetchError, match="invalid JSON"):
            await run_fetch()


async def test_http_error_raises():
    with respx.mock:
        respx.get(SEARCH).respond(403)
        with pytest.raises(FetchError, match="403"):
            await run_fetch()


async def test_posting_links_use_public_host_while_search_uses_the_search_host():
    company = Company(
        name="Acme",
        slug="acme",
        tier=1,
        ats="eightfold",
        ats_config={
            "host": "acme.eightfold.ai",
            "domain": "acme.com",
            "public_host": "careers.acme.com",
        },
        enabled=True,
    )
    body = {"data": {"count": 1, "positions": [position(1)]}}
    with respx.mock:
        route = respx.get("https://acme.eightfold.ai/api/pcsx/search").respond(200, json=body)
        async with make_client(delay=0, backoff=0) as client:
            [p] = await eightfold.fetch(company, client)
    assert route.called  # the search went to the plain Eightfold host
    assert p.url.startswith("https://careers.acme.com/")
