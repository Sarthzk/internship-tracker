import json
from datetime import date

import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher
from tracker.fetchers.custom import google
from tracker.http import make_client
from tracker.models import Company

COMPANY = Company(name="Google", slug="google", tier=1, ats="custom", ats_config={}, enabled=True)


def job(n: int, title: str | None = None) -> list:
    record: list = [None] * 21
    record[0] = f"1000{n}"
    record[1] = title or f"Software Engineering Intern {n}"
    record[3] = [None, "<ul>long description that must not be kept</ul>"]
    record[9] = [["Bengaluru, Karnataka, India", ["Bengaluru, Karnataka, India"], "Bengaluru"]]
    record[12] = [1793171396, 528000000]
    return record


def page(jobs: list | None, total: int | None = None, size: int = 20) -> str:
    total = (len(jobs) if jobs else 0) if total is None else total
    block = json.dumps([jobs, None, total, size])
    return f"<script>AF_initDataCallback({{key: 'ds:1', hash: '5', data:{block}, sideChannel: {{}}}});</script>"


async def run():
    async with make_client(delay=0, backoff=0) as client:
        return await google.fetch(COMPANY, client)


def test_registered():
    assert get_fetcher(COMPANY) is google.fetch


async def test_normalizes_and_asks_for_india_interns():
    with respx.mock:
        route = respx.get(google.SEARCH).respond(200, text=page([job(1)]))
        [p] = await run()
    params = route.calls.last.request.url.params
    assert params["q"] == "intern" and params["location"] == "India" and params["page"] == "1"
    assert p.external_id == "10001" and p.title == "Software Engineering Intern 1"
    assert p.locations == ["Bengaluru, Karnataka, India"]
    assert p.url == "https://www.google.com/about/careers/applications/jobs/results/10001"
    assert p.date_posted == date(2026, 10, 28)
    assert "description" not in json.dumps(p.model_dump(), default=str).lower()


async def test_pages_until_total():
    with respx.mock:
        route = respx.get(google.SEARCH).mock(
            side_effect=[
                respx.MockResponse(200, text=page([job(1), job(2)], total=3, size=2)),
                respx.MockResponse(200, text=page([job(3)], total=3, size=2)),
            ]
        )
        postings = await run()
    assert len(postings) == 3
    assert [c.request.url.params["page"] for c in route.calls] == ["1", "2"]


async def test_no_matches_is_empty():
    with respx.mock:
        respx.get(google.SEARCH).respond(200, text=page(None))
        assert await run() == []


@pytest.mark.parametrize(
    "response",
    [
        respx.MockResponse(200, text="<html>layout changed</html>"),
        respx.MockResponse(200, text=page([], total=3)),  # claims 3, gives none
        respx.MockResponse(
            200,
            text="<script>AF_initDataCallback({key: 'ds:1', hash: '5', data:[1], sideChannel: {}});</script>",
        ),
        respx.MockResponse(200, text=page([["short"]])),
        respx.MockResponse(503),
    ],
)
async def test_unexpected_response_raises(response):
    with respx.mock:
        respx.get(google.SEARCH).mock(return_value=response)
        with pytest.raises(FetchError):
            await run()
