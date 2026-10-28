from datetime import date

import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher
from tracker.fetchers.custom import quadeye
from tracker.http import make_client
from tracker.models import Company

COMPANY = Company(name="Quadeye", slug="quadeye", tier=1, ats="custom", ats_config={}, enabled=True)


def opening(n: int, **overrides) -> dict:
    data = {
        "id": f"19989300000{n}",
        "Posting_Title": f"Intern - Systems Engineer {n}",
        "City": "Gurgaon",
        "State": "Haryana",
        "Country": "India",
        "Date_Opened": "2026-06-29",
        "Publish": "True",
        "Required_Skills": "long text that must not be kept",
    }
    data.update(overrides)
    return data


async def run():
    async with make_client(delay=0, backoff=0) as client:
        return await quadeye.fetch(COMPANY, client)


def test_registered():
    assert get_fetcher(COMPANY) is quadeye.fetch


async def test_normalizes():
    with respx.mock:
        respx.get(quadeye.API).respond(200, json={"success": True, "data": [opening(1)]})
        [p] = await run()
    assert p.external_id == "199893000001" and p.title == "Intern - Systems Engineer 1"
    assert p.locations == ["Gurgaon, Haryana, India"]
    assert p.url == "https://quadeye.zohorecruit.in/jobs/Careers/199893000001"
    assert p.date_posted == date(2026, 6, 29)
    assert "Required_Skills" not in p.model_dump()


async def test_skips_unpublished_and_ignores_none_places():
    jobs = [opening(1, Publish="False"), opening(2, City="None", State="None", Country="India")]
    with respx.mock:
        respx.get(quadeye.API).respond(200, json={"data": jobs})
        [p] = await run()
    assert p.external_id == "199893000002" and p.locations == ["India"]


async def test_empty_is_empty():
    with respx.mock:
        respx.get(quadeye.API).respond(200, json={"data": []})
        assert await run() == []


@pytest.mark.parametrize("payload", [{"data": "no"}, {}, [], {"data": [{"Posting_Title": "x"}]}])
async def test_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(quadeye.API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run()
