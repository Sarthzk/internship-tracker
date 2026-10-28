from datetime import date

import pytest
import respx

from tracker.fetchers import FetchError, get_fetcher
from tracker.fetchers.custom import amazon, atlassian, goldman
from tracker.http import make_client
from tracker.models import Company


def company(slug: str) -> Company:
    return Company(name=slug.title(), slug=slug, tier=1, ats="custom", ats_config={}, enabled=True)


async def run(module, slug: str):
    async with make_client(delay=0, backoff=0) as client:
        return await module.fetch(company(slug), client)


@pytest.mark.parametrize(
    "module,slug", [(amazon, "amazon"), (atlassian, "atlassian"), (goldman, "goldman-sachs")]
)
def test_registered_by_slug(module, slug):
    assert get_fetcher(company(slug)) is module.fetch


# --- Amazon ---


def amazon_job(n: int, **overrides) -> dict:
    data = {
        "id_icims": f"1049{n}",
        "id": f"uuid-{n}",
        "title": f"Software Development Engineer Intern {n}",
        "normalized_location": "Bengaluru, Karnataka, IND",
        "job_path": f"/en/jobs/1049{n}/sde-intern",
        "posted_date": "August 11, 2026",
        "description": "long text that must not be kept",
    }
    data.update(overrides)
    return data


async def test_amazon_normalizes_and_asks_for_india_interns():
    body = {"error": None, "hits": 1, "jobs": [amazon_job(1)]}
    with respx.mock:
        route = respx.get(amazon.API).respond(200, json=body)
        [p] = await run(amazon, "amazon")
    params = route.calls.last.request.url.params
    assert params["base_query"] == "intern" and params["country"] == "IND"
    assert params["loc_query"] == "India" and params["offset"] == "0"
    assert p.external_id == "10491" and p.source == "custom"
    assert p.locations == ["Bengaluru, Karnataka, India"]  # IND rewritten so the filter matches
    assert p.url == "https://www.amazon.jobs/en/jobs/10491/sde-intern"
    assert p.date_posted == date(2026, 8, 11)
    assert "description" not in p.model_dump()


async def test_amazon_pages_by_offset():
    with respx.mock:
        route = respx.get(amazon.API).mock(
            side_effect=[
                respx.MockResponse(200, json={"hits": 3, "jobs": [amazon_job(1), amazon_job(2)]}),
                respx.MockResponse(200, json={"hits": 3, "jobs": [amazon_job(3)]}),
            ]
        )
        postings = await run(amazon, "amazon")
    assert len(postings) == 3
    assert [c.request.url.params["offset"] for c in route.calls] == ["0", "2"]


async def test_amazon_bad_date_and_empty():
    with respx.mock:
        respx.get(amazon.API).respond(
            200, json={"hits": 1, "jobs": [amazon_job(1, posted_date="soon")]}
        )
        [p] = await run(amazon, "amazon")
    assert p.date_posted is None
    with respx.mock:
        respx.get(amazon.API).respond(200, json={"hits": 0, "jobs": []})
        assert await run(amazon, "amazon") == []


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "x"},
        {"hits": 1, "jobs": "no"},
        {"jobs": []},
        {"hits": 1, "jobs": [{"title": "x"}]},
    ],
)
async def test_amazon_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(amazon.API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run(amazon, "amazon")


# --- Atlassian ---


def atlassian_job(n: int, **overrides) -> dict:
    data = {
        "id": 26270 + n,
        "title": f"Software Engineer Intern {n}",
        "locations": ["Bengaluru - India -   Bengaluru,  560071 India"],
        "portalJobPost": {"portalUrl": f"https://campus.icims.com/jobs/{26270 + n}/intern/job"},
        "applyUrl": f"https://campus.icims.com/jobs/{26270 + n}/intern/job?mode=apply",
        "overview": "long text that must not be kept",
    }
    data.update(overrides)
    return data


async def test_atlassian_normalizes_and_prefers_public_portal_url():
    with respx.mock:
        respx.get(atlassian.API).respond(200, json=[atlassian_job(1)])
        [p] = await run(atlassian, "atlassian")
    assert p.external_id == "26271" and p.title == "Software Engineer Intern 1"
    assert p.locations == ["Bengaluru - India -   Bengaluru,  560071 India"]
    assert p.url == "https://campus.icims.com/jobs/26271/intern/job"


async def test_atlassian_falls_back_to_apply_url_and_handles_remote():
    job = atlassian_job(1, portalJobPost=None, locations=["Remote - India - Remote"])
    with respx.mock:
        respx.get(atlassian.API).respond(200, json=[job])
        [p] = await run(atlassian, "atlassian")
    assert p.url.endswith("?mode=apply") and p.is_remote


@pytest.mark.parametrize(
    "payload",
    [{"error": "x"}, [{"title": "No id"}], [atlassian_job(1, portalJobPost=None, applyUrl=None)]],
)
async def test_atlassian_unexpected_shape_raises(payload):
    with respx.mock:
        respx.get(atlassian.API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run(atlassian, "atlassian")


# --- Goldman Sachs ---


def goldman_role(n: int, **overrides) -> dict:
    data = {
        "roleId": f"17359{n}_GS_EARLY_CAREER",
        "jobTitle": f"Engineering Summer Analyst {n}",
        "locations": [{"city": "Bengaluru", "state": "Karnataka", "country": "India"}],
    }
    data.update(overrides)
    return data


def goldman_body(roles: list[dict], total: int | None = None) -> dict:
    count = len(roles) if total is None else total
    return {"data": {"roleSearch": {"totalCount": count, "items": roles}}}


async def test_goldman_normalizes_and_asks_for_early_career_roles():
    with respx.mock:
        route = respx.post(goldman.API).respond(200, json=goldman_body([goldman_role(1)]))
        [p] = await run(goldman, "goldman-sachs")
    sent = route.calls.last.request.content
    assert b"EARLY_CAREER" in sent and b"roleSearch" in sent
    assert p.external_id == "173591_GS_EARLY_CAREER" and p.title == "Engineering Summer Analyst 1"
    assert p.locations == ["Bengaluru, Karnataka, India"]
    assert p.url == "https://higher.gs.com/roles/173591_GS_EARLY_CAREER"


async def test_goldman_pages_by_page_number():
    with respx.mock:
        route = respx.post(goldman.API).mock(
            side_effect=[
                respx.MockResponse(200, json=goldman_body([goldman_role(1), goldman_role(2)], 3)),
                respx.MockResponse(200, json=goldman_body([goldman_role(3)], 3)),
            ]
        )
        postings = await run(goldman, "goldman-sachs")
    assert len(postings) == 3 and route.call_count == 2


async def test_goldman_graphql_errors_fail_loudly():
    with respx.mock:
        respx.post(goldman.API).respond(200, json={"errors": [{"message": "Unknown field"}]})
        with pytest.raises(FetchError, match="schema"):
            await run(goldman, "goldman-sachs")


@pytest.mark.parametrize(
    "payload",
    [
        {"data": None},
        {"data": {"roleSearch": {"items": "no", "totalCount": 1}}},
        {"data": {"roleSearch": {"items": [], "totalCount": "many"}}},
        goldman_body([{"jobTitle": "No id"}]),
    ],
)
async def test_goldman_unexpected_shape_raises(payload):
    with respx.mock:
        respx.post(goldman.API).respond(200, json=payload)
        with pytest.raises(FetchError):
            await run(goldman, "goldman-sachs")
