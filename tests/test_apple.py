import json
from datetime import date

import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher
from tracker.fetchers.custom import apple
from tracker.http import make_client
from tracker.models import Company

COMPANY = Company(name="Apple", slug="apple", tier=1, ats="custom", ats_config={}, enabled=True)


def role(n: int, **overrides) -> dict:
    data = {
        "positionId": f"20000{n}",
        "postingTitle": f"Software Engineering Intern {n}",
        "transformedPostingTitle": f"software-engineering-intern-{n}",
        "postDateInGMT": "2026-10-28T17:21:05.343185917Z",
        "locations": [{"name": "Bengaluru", "countryName": "India"}],
        "team": {"teamCode": "SFTWR"},
        "jobSummary": "long text that must not be kept",
    }
    data.update(overrides)
    return data


def page(roles: list[dict], total: int | None = None) -> str:
    state = {
        "loaderData": {
            "search": {
                "searchResults": roles,
                "totalRecords": len(roles) if total is None else total,
            }
        }
    }
    literal = json.dumps(json.dumps(state))[1:-1]  # the JSON as the inside of a JS string literal
    return f'<html><script>window.__staticRouterHydrationData = JSON.parse("{literal}");</script>'


async def run():
    async with make_client(delay=0, backoff=0) as client:
        return await apple.fetch(COMPANY, client)


def test_registered():
    assert get_fetcher(COMPANY) is apple.fetch


async def test_normalizes_and_asks_for_india_intern():
    with respx.mock:
        route = respx.get(apple.SEARCH).respond(200, text=page([role(1)]))
        [p] = await run()
    params = route.calls.last.request.url.params
    assert params["location"] == "india-INDC" and params["search"] == "intern"
    assert p.external_id == "200001" and p.source == "custom"
    assert p.title == "Software Engineering Intern 1"
    assert p.locations == ["Bengaluru, India"]
    assert (
        p.url
        == "https://jobs.apple.com/en-in/details/200001/software-engineering-intern-1?team=SFTWR"
    )
    assert p.date_posted == date(2026, 10, 28)
    assert "jobSummary" not in p.model_dump()


async def test_pages_until_total():
    with respx.mock:
        route = respx.get(apple.SEARCH).mock(
            side_effect=[
                respx.MockResponse(200, text=page([role(1), role(2)], total=3)),
                respx.MockResponse(200, text=page([role(3)], total=3)),
            ]
        )
        postings = await run()
    assert len(postings) == 3
    assert [c.request.url.params["page"] for c in route.calls] == ["1", "2"]


async def test_no_matches_is_empty():
    with respx.mock:
        respx.get(apple.SEARCH).respond(200, text=page([]))
        assert await run() == []


@pytest.mark.parametrize(
    "response",
    [
        respx.MockResponse(200, text="<html>layout changed</html>"),
        respx.MockResponse(200, text=page([], total=4)),  # fewer roles than claimed
        respx.MockResponse(200, text=page([{"postingTitle": "x"}])),
        respx.MockResponse(503),
    ],
)
async def test_unexpected_response_raises(response):
    with respx.mock:
        respx.get(apple.SEARCH).mock(return_value=response)
        with pytest.raises(FetchError):
            await run()
