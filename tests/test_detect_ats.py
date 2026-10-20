import httpx
import pytest
import respx

from scripts.detect_ats import (
    USER_AGENT,
    detect,
    get_json,
    is_india,
    parse_ashby,
    parse_greenhouse,
    parse_lever,
    parse_smartrecruiters,
    render_report,
    slug_guesses,
)
from tracker.models import Company


def company(name: str, slug: str) -> Company:
    return Company(name=name, slug=slug, tier=1, ats="unknown")


# --- slug guesses ---


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Stripe", ["stripe"]),
        ("Walmart Global Tech", ["walmartglobaltech", "walmart-global-tech", "walmart"]),
        ("Tower Research Capital", ["towerresearchcapital", "tower-research-capital", "tower"]),
        ("D. E. Shaw", ["deshaw", "d-e-shaw", "de-shaw", "deshawresearch"]),
        ("Media.net", ["medianet", "media-net"]),
        ("JPMorgan Chase", ["jpmorganchase", "jpmorgan-chase", "jpmorgan"]),
    ],
)
def test_slug_guesses(name, expected):
    guesses = slug_guesses(name)
    for slug in dict.fromkeys(expected):
        assert slug in guesses
    assert len(guesses) == len(set(guesses))


def test_slug_guesses_strip_suffix():
    assert "towerresearch" in slug_guesses("Tower Research Capital")
    assert "graviton-research" in slug_guesses("Graviton Research Capital")


# --- India matcher ---


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Bengaluru, Karnataka, India", True),
        ("Remote - India", True),
        ("Gurgaon", True),
        ("Indianapolis, IN", False),
        ("Indiana", False),
        ("San Francisco, CA", False),
        (None, False),
    ],
)
def test_is_india(text, expected):
    assert is_india(text) is expected


# --- parsers ---


def test_parse_greenhouse():
    board = parse_greenhouse(
        {
            "jobs": [
                {"location": {"name": "Bengaluru, India"}, "company_name": "Stripe"},
                {"location": {"name": "Dublin"}, "company_name": "Stripe"},
            ]
        }
    )
    assert (board.total, board.india, board.api_company_name) == (2, 1, "Stripe")


def test_parse_lever():
    board = parse_lever(
        [
            {"categories": {"location": "Remote", "allLocations": ["Remote", "Pune"]}},
            {"categories": {"location": "London"}},
        ]
    )
    assert (board.total, board.india) == (2, 1)


def test_parse_ashby():
    board = parse_ashby(
        {
            "jobs": [
                {"location": "New York", "secondaryLocations": [{"location": "Hyderabad"}]},
                {"location": "Berlin"},
            ]
        }
    )
    assert (board.total, board.india) == (2, 1)


def test_parse_smartrecruiters_marks_partial():
    board = parse_smartrecruiters(
        {
            "totalFound": 250,
            "content": [
                {"location": {"country": "in", "city": "Noida"}, "company": {"name": "Visa"}},
                {"location": {"country": "us", "city": "Austin"}, "company": {"name": "Visa"}},
            ],
        }
    )
    assert (board.total, board.india, board.partial) == (250, 1, True)
    assert board.api_company_name == "Visa"


@pytest.mark.parametrize(
    "parser,data",
    [
        (parse_greenhouse, {"error": "not found"}),
        (parse_lever, {"ok": False}),
        (parse_ashby, []),
        (parse_smartrecruiters, None),
    ],
)
def test_parsers_reject_unexpected_shapes(parser, data):
    assert parser(data) is None


# --- HTTP ---


@respx.mock
async def test_get_json_retries_on_503(monkeypatch):
    monkeypatch.setattr("scripts.detect_ats.asyncio.sleep", _no_sleep)
    route = respx.get("https://example.com/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    async with httpx.AsyncClient() as client:
        assert await get_json(client, "https://example.com/x") == (200, {"ok": True})
    assert route.call_count == 2


@respx.mock
async def test_get_json_does_not_retry_404():
    route = respx.get("https://example.com/x").mock(return_value=httpx.Response(404))
    async with httpx.AsyncClient() as client:
        status, _ = await get_json(client, "https://example.com/x")
    assert status == 404
    assert route.call_count == 1


async def _no_sleep(_seconds: float) -> None:
    return None


@respx.mock
async def test_detect_end_to_end():
    stripe, acme = company("Stripe", "stripe"), company("Acme Corp", "acme-corp")
    gh = respx.get("https://boards-api.greenhouse.io/v1/boards/stripe/jobs").mock(
        return_value=httpx.Response(
            200, json={"jobs": [{"location": {"name": "Bengaluru, India"}}]}
        )
    )
    sr_empty = respx.get(
        url__regex=r"https://api\.smartrecruiters\.com/v1/companies/acme.*/postings.*"
    ).mock(return_value=httpx.Response(200, json={"totalFound": 0, "content": []}))
    respx.route().mock(return_value=httpx.Response(404))

    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        results = await detect([stripe, acme], client, delay=0)

    assert gh.called
    assert gh.calls[0].request.headers["User-Agent"] == USER_AGENT
    assert sr_empty.called
    matches = [r for r in results if r.is_match]
    assert [(r.company.slug, r.spec.ats, r.slug) for r in matches] == [
        ("stripe", "greenhouse", "stripe")
    ]

    report = render_report([stripe, acme], results)
    assert "## Detected (1 of 2 companies)" in report
    assert "`ats: greenhouse, ats_config: {board_token: stripe}`" in report
    assert "| Acme Corp | smartrecruiters/`acmecorp`" in report
