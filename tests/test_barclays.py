import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher
from tracker.fetchers.custom import barclays
from tracker.http import make_client
from tracker.models import Company

COMPANY = Company(
    name="Barclays", slug="barclays", tier=1, ats="custom", ats_config={}, enabled=True
)


def job(n: int, title: str = "Tech Intern", place: str = "Pune, India") -> str:
    return (
        f'<div class="card"><a href="/job/pune/x-{n}/13015/{n}" class="job-title--link" '
        f'data-job-id="{n}"><strong>{title} {n}</strong></a>\r\n'
        f'<div class="job-location">\r\n{place}</div></div>'
    )


def page(jobs: list[str], total: int | None = None, pages: int = 1) -> dict:
    total = len(jobs) if total is None else total
    head = f'<div id="search-results" data-total-job-results="{total}" data-total-pages="{pages}">'
    return {"results": head + "".join(jobs) + "</div>", "hasJobs": True}


async def run():
    async with make_client(delay=0, backoff=0) as client:
        return await barclays.fetch(COMPANY, client)


def test_registered():
    assert get_fetcher(COMPANY) is barclays.fetch


async def test_parses_jobs_and_asks_for_intern():
    with respx.mock:
        route = respx.get(barclays.API).respond(200, json=page([job(1), job(2, "R&amp;D Intern")]))
        postings = await run()
    params = route.calls.last.request.url.params
    assert params["Keywords"] == "intern" and params["CurrentPage"] == "1"
    assert [p.external_id for p in postings] == ["1", "2"]
    assert postings[1].title == "R&D Intern 2"
    assert postings[0].locations == ["Pune, India"]
    assert postings[0].url == "https://search.jobs.barclays/job/pune/x-1/13015/1"


async def test_pages_until_last_page():
    with respx.mock:
        route = respx.get(barclays.API).mock(
            side_effect=[
                respx.MockResponse(200, json=page([job(1)], total=2, pages=2)),
                respx.MockResponse(200, json=page([job(2)], total=2, pages=2)),
            ]
        )
        postings = await run()
    assert len(postings) == 2
    assert [c.request.url.params["CurrentPage"] for c in route.calls] == ["1", "2"]


async def test_no_matches_is_empty():
    with respx.mock:
        respx.get(barclays.API).respond(200, json=page([]))
        assert await run() == []


@pytest.mark.parametrize(
    "payload",
    [
        {"results": 5},
        {"results": "<div>layout changed</div>"},
        page([job(1)], total=3),  # parsed fewer jobs than the page claims
    ],
)
async def test_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(barclays.API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run()
