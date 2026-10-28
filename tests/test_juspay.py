import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher
from tracker.fetchers.custom import juspay
from tracker.http import make_client
from tracker.models import Company

COMPANY = Company(name="Juspay", slug="juspay", tier=2, ats="custom", ats_config={}, enabled=True)


def opening(job_id: str, title: str, job_type: str = "Full-Time", **overrides) -> dict:
    data = {
        "job_id": job_id,
        "job_title": title,
        "job_type": job_type,
        "job_location": "Bangalore",
        "opening_status": "True",
        "job_description_career": "long text that must not be kept",
    }
    data.update(overrides)
    return data


async def run():
    async with make_client(delay=0, backoff=0) as client:
        return await juspay.fetch(COMPANY, client)


def test_registered():
    assert get_fetcher(COMPANY) is juspay.fetch


async def test_marks_intern_job_type_in_title():
    jobs = [
        opening("DEV-BE02", "Software Development Engineer Backend", "Intern"),
        opening("LI01", "Legal Intern", "Intern"),
        opening("SRE04", "Site Reliability Engineer"),
    ]
    with respx.mock:
        route = respx.get(juspay.API).respond(200, json={"allJobs": jobs, "summary": {}})
        postings = await run()
    assert route.calls.last.request.url.params["limit"] == "1000"
    assert [p.title for p in postings] == [
        "Software Development Engineer Backend Intern",
        "Legal Intern",
        "Site Reliability Engineer",
    ]
    first = postings[0]
    assert first.external_id == "DEV-BE02" and first.locations == ["Bangalore"]
    assert first.url == "https://joinus.juspay.in/?jobId=DEV-BE02"
    assert "job_description_career" not in first.model_dump()


async def test_closed_openings_are_skipped():
    with respx.mock:
        respx.get(juspay.API).respond(
            200, json={"allJobs": [opening("A1", "X", opening_status="False"), opening("A2", "Y")]}
        )
        [p] = await run()
    assert p.external_id == "A2"


async def test_empty_is_empty():
    with respx.mock:
        respx.get(juspay.API).respond(200, json={"allJobs": []})
        assert await run() == []


@pytest.mark.parametrize("payload", [{"allJobs": "no"}, {}, [], {"allJobs": [{"job_title": "x"}]}])
async def test_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(juspay.API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run()
