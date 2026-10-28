from datetime import date

import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher
from tracker.fetchers.phenom import fetch
from tracker.http import make_client
from tracker.models import Company

COMPANY = Company(
    name="Adobe",
    slug="adobe",
    tier=1,
    ats="phenom",
    ats_config={"host": "careers.adobe.com"},
    enabled=True,
)
URL = "https://careers.adobe.com/widgets"


def job(n: int, **overrides) -> dict:
    data = {
        "jobId": f"R{n}",
        "title": f"2027 Intern {n}",
        "multi_location": ["Bangalore, Karnātaka, India"],
        "location": "Bangalore, Karnātaka, India",
        "postedDate": "2026-10-19T00:00:00.000+0000",
        "descriptionTeaser": "long text that must not be kept",
    }
    data.update(overrides)
    return data


def reply(jobs: list[dict], total: int | None = None) -> dict:
    total = len(jobs) if total is None else total
    return {"refineSearch": {"totalHits": total, "data": {"jobs": jobs}}}


async def run():
    async with make_client(delay=0, backoff=0) as client:
        return await fetch(COMPANY, client)


def test_registered_for_phenom():
    assert get_fetcher(COMPANY) is fetch


async def test_normalizes_and_asks_for_india_interns():
    with respx.mock:
        route = respx.post(URL).respond(200, json=reply([job(1)]))
        [p] = await run()
    body = route.calls.last.request.read().decode()
    assert '"keywords":"intern"' in body.replace(" ", "") and "India" in body
    assert p.external_id == "R1" and p.source == "phenom" and p.title == "2027 Intern 1"
    assert p.locations == ["Bangalore, Karnātaka, India"]
    assert p.url == "https://careers.adobe.com/us/en/job/R1"
    assert p.date_posted == date(2026, 10, 19)
    assert "descriptionTeaser" not in p.model_dump()


async def test_falls_back_to_single_location_and_custom_locale():
    company = COMPANY.model_copy(
        update={"ats_config": {"host": "careers.adobe.com", "locale": "in/en"}}
    )
    with respx.mock:
        respx.post(URL).respond(200, json=reply([job(1, multi_location=None)]))
        async with make_client(delay=0, backoff=0) as client:
            [p] = await fetch(company, client)
    assert p.locations == ["Bangalore, Karnātaka, India"]
    assert p.url == "https://careers.adobe.com/in/en/job/R1"


async def test_pages_until_total_hits():
    jobs = [job(n) for n in range(60)]
    with respx.mock:
        route = respx.post(URL).mock(
            side_effect=[
                respx.MockResponse(200, json=reply(jobs[:50], total=60)),
                respx.MockResponse(200, json=reply(jobs[50:], total=60)),
            ]
        )
        postings = await run()
    assert len(postings) == 60 and route.call_count == 2


async def test_no_matches_is_empty():
    with respx.mock:
        respx.post(URL).respond(200, json=reply([]))
        assert await run() == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"refineSearch": {"data": {"jobs": "no"}, "totalHits": 1}},
        {"refineSearch": {"data": {"jobs": []}}},
        reply([], total=3),  # claims 3, returns none
        reply([{"title": "x"}]),
    ],
)
async def test_unexpected_shape_raises(payload):
    with respx.mock:
        respx.post(URL).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run()
