import json
from datetime import date
from pathlib import Path

import pytest
import respx

from tracker.fetchers import FetchError, ashby, get_fetcher, greenhouse, lever
from tracker.http import make_client
from tracker.models import Company

FIXTURES = Path(__file__).parent / "fixtures" / "fetchers"


def load(name: str):
    return json.loads((FIXTURES / name).read_text())


def company(ats: str, config: dict) -> Company:
    return Company(name="Acme", slug="acme", tier=1, ats=ats, ats_config=config, enabled=True)


def test_greenhouse_normalizes():
    postings = greenhouse.normalize(
        company("greenhouse", {"board_token": "acme"}), load("greenhouse.json")
    )
    assert [p.external_id for p in postings] == ["7001", "7002", "7003"]
    first = postings[0]
    assert first.source == "greenhouse" and first.company_slug == "acme"
    assert first.locations == ["Bengaluru, India"]
    assert first.date_posted == date(2026, 10, 1)
    assert postings[1].is_remote and postings[1].date_posted is None
    assert postings[2].locations == []


def test_lever_normalizes():
    postings = lever.normalize(company("lever", {"site": "acme"}), load("lever.json"))
    first, second = postings
    assert first.locations == ["Pune", "Mumbai"]
    assert first.date_posted == date(2026, 9, 21)
    assert first.description == "Work on models."
    assert second.is_remote and second.locations == ["Remote"]
    assert second.date_posted is None


def test_ashby_normalizes_and_skips_unlisted():
    postings = ashby.normalize(company("ashby", {"site": "acme"}), load("ashby.json"))
    assert [p.external_id for p in postings] == ["cc-3333"]
    assert postings[0].locations == ["Hyderabad", "Remote - India"]
    assert postings[0].date_posted == date(2026, 10, 5)
    assert postings[0].is_remote


@pytest.mark.parametrize("module", [greenhouse, lever, ashby])
def test_unexpected_shape_raises_instead_of_returning_empty(module):
    c = company(module.__name__.rsplit(".", 1)[1], {"board_token": "x", "site": "x"})
    with pytest.raises(FetchError):
        module.normalize(c, {"error": "nope"} if module is lever else "garbage")


def test_descriptions_are_not_serialized():
    postings = lever.normalize(company("lever", {"site": "acme"}), load("lever.json"))
    assert "Work on models" not in postings[0].model_dump_json()


async def test_greenhouse_fetch_over_http():
    c = company("greenhouse", {"board_token": "acme"})
    with respx.mock:
        respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").respond(
            200, json=load("greenhouse.json")
        )
        async with make_client(delay=0, backoff=0) as client:
            postings = await get_fetcher(c)(c, client)
    assert len(postings) == 3


async def test_http_error_raises_fetch_error():
    c = company("lever", {"site": "acme"})
    with respx.mock:
        respx.get("https://api.lever.co/v0/postings/acme").respond(404)
        async with make_client(delay=0, backoff=0) as client:
            with pytest.raises(FetchError, match="404"):
                await get_fetcher(c)(c, client)


def test_registry_has_no_fetcher_for_unknown_ats():
    c = company("unknown", {})
    assert get_fetcher(c) is None
