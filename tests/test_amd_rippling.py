from datetime import date

import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher
from tracker.fetchers.custom import amd, rippling
from tracker.http import make_client
from tracker.models import Company


def company(slug: str) -> Company:
    return Company(name=slug.title(), slug=slug, tier=1, ats="custom", ats_config={}, enabled=True)


async def run(module, slug: str):
    async with make_client(delay=0, backoff=0) as client:
        return await module.fetch(company(slug), client)


def test_registered_by_slug():
    assert get_fetcher(company("amd")) is amd.fetch
    assert get_fetcher(company("rippling")) is rippling.fetch


# --- AMD ---


def amd_job(n: int, **overrides) -> dict:
    data = {
        "slug": f"9{n}",
        "req_id": f"9{n}",
        "title": f"Software Engineer Intern {n}",
        "full_location": "Bengaluru, Karnataka",
        "country": "India",
        "posted_date": "2026-08-20T23:28:00+0000",
        "description": "long text that must not be kept",
    }
    data.update(overrides)
    return {"data": data}


def amd_page(jobs: list[dict], total: int | None = None) -> dict:
    return {"jobs": jobs, "totalCount": len(jobs) if total is None else total}


async def test_amd_normalizes():
    with respx.mock:
        route = respx.get(amd.API).respond(200, json=amd_page([amd_job(1)]))
        [p] = await run(amd, "amd")
    params = route.calls.last.request.url.params
    assert params["keywords"] == "intern" and params["page"] == "1"
    assert p.external_id == "91" and p.source == "custom"
    assert p.locations == ["Bengaluru, Karnataka, India"]
    assert p.url == "https://careers.amd.com/careers-home/jobs/91"
    assert p.date_posted == date(2026, 8, 20)
    assert "description" not in p.model_dump()


async def test_amd_pages_until_total():
    with respx.mock:
        route = respx.get(amd.API).mock(
            side_effect=[
                respx.MockResponse(200, json=amd_page([amd_job(1), amd_job(2)], total=3)),
                respx.MockResponse(200, json=amd_page([amd_job(3)], total=3)),
            ]
        )
        postings = await run(amd, "amd")
    assert len(postings) == 3
    assert [c.request.url.params["page"] for c in route.calls] == ["1", "2"]


async def test_amd_no_matches_is_empty():
    with respx.mock:
        respx.get(amd.API).respond(200, json=amd_page([]))
        assert await run(amd, "amd") == []


async def test_amd_short_result_raises():
    with respx.mock:
        respx.get(amd.API).respond(200, json=amd_page([], total=5))
        with pytest.raises(FetchError):
            await run(amd, "amd")


@pytest.mark.parametrize(
    "payload",
    [
        {"jobs": "no", "totalCount": 1},
        {"jobs": []},
        {"jobs": [{"data": {"title": "x"}}], "totalCount": 1},
    ],
)
async def test_amd_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(amd.API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run(amd, "amd")


# --- Rippling ---


def rippling_job(n: int, **overrides) -> dict:
    data = {
        "id": f"id-{n}",
        "name": f"Software Engineer Intern {n}",
        "url": f"https://ats.rippling.com/rippling/jobs/id-{n}",
        "locations": [
            {"name": "Bengaluru", "country": "India", "workplaceType": "ON_SITE"},
            {"name": "Remote (US)", "country": "United States", "workplaceType": "REMOTE"},
        ],
    }
    data.update(overrides)
    return data


async def test_rippling_normalizes_and_searches_for_intern():
    body = {"items": [rippling_job(1)], "totalPages": 1}
    with respx.mock:
        route = respx.get(rippling.API).respond(200, json=body)
        [p] = await run(rippling, "rippling")
    params = route.calls.last.request.url.params
    assert params["searchQuery"] == "intern" and params["page"] == "0"
    assert p.external_id == "id-1" and p.title == "Software Engineer Intern 1"
    assert p.locations == ["Bengaluru, India", "Remote (US), United States"]
    assert p.is_remote is True
    assert p.url == "https://ats.rippling.com/rippling/jobs/id-1"


async def test_rippling_pages_by_total_pages():
    with respx.mock:
        route = respx.get(rippling.API).mock(
            side_effect=[
                respx.MockResponse(200, json={"items": [rippling_job(1)], "totalPages": 2}),
                respx.MockResponse(200, json={"items": [rippling_job(2)], "totalPages": 2}),
            ]
        )
        postings = await run(rippling, "rippling")
    assert len(postings) == 2
    assert [c.request.url.params["page"] for c in route.calls] == ["0", "1"]


async def test_rippling_no_matches_is_empty():
    with respx.mock:
        respx.get(rippling.API).respond(200, json={"items": [], "totalPages": 0})
        assert await run(rippling, "rippling") == []


@pytest.mark.parametrize(
    "payload",
    [{"items": "no", "totalPages": 1}, {"items": []}, {"items": [{"name": "x"}], "totalPages": 1}],
)
async def test_rippling_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(rippling.API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run(rippling, "rippling")
