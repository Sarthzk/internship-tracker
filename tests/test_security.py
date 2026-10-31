"""Worst cases: scam links, hostile text, floods, leaked secrets, oversized responses."""

import json
import logging
from datetime import timedelta

import httpx
import pytest
import respx

from tests.test_main import GH, LV, T0, FakeSender, companies, go, old_health
from tracker.enrich import Extraction, validate
from tracker.http import PoliteTransport, ResponseTooLarge, make_client
from tracker.linkcheck import is_allowed
from tracker.models import Company
from tracker.notify import Telegram, format_listing
from tracker.readme import generate, render_listings
from tracker.storage import load_listings

ACME = companies()[0]  # greenhouse, board token "acme"


def gh(*jobs: tuple[int, str, str]) -> dict:
    return {
        "jobs": [
            {"id": n, "title": title, "absolute_url": url, "location": {"name": "Pune"}}
            for n, title, url in jobs
        ]
    }


# --- scam links ---


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://job-boards.greenhouse.io/acme/jobs/1", True),
        ("https://boards.greenhouse.io/acme/jobs/1", True),
        ("https://job-boards.eu.greenhouse.io/acme/jobs/1", True),
        ("http://job-boards.greenhouse.io/acme/jobs/1", False),  # not https
        ("https://greenhouse.io.evil.com/acme", False),  # look-alike suffix
        ("https://evilgreenhouse.io/acme", False),  # look-alike name
        ("https://job-boards.greenhouse.io@evil.com/acme", False),  # user-info trick
        ("javascript:alert(1)", False),
        ("data:text/html,hi", False),
        ("https://bit.ly/xyz", False),
    ],
)
def test_links_must_be_on_an_expected_host(url, ok):
    assert is_allowed(url, ACME) is ok


def test_link_hosts_extend_the_allowed_hosts_and_must_be_plain_hostnames():
    company = ACME.model_copy(update={"link_hosts": ["careers.acme.com"]})
    assert is_allowed("https://careers.acme.com/jobs/1", company)
    for bad in ("https://evil.com", "evil.com/path", "localhost", "1.2.3.4", "*.acme.com"):
        with pytest.raises(ValueError):
            Company(**{**ACME.model_dump(), "link_hosts": [bad]})


async def test_unexpected_link_is_held_from_channel_and_readme_and_owner_told_once(tmp_path):
    old_health(tmp_path)
    owner, channel = FakeSender(), FakeSender()
    jobs = gh(
        (1, "Software Engineer Intern", "https://job-boards.greenhouse.io/acme/jobs/1"),
        (2, "Data Science Intern", "https://acme-careers.example/apply/2"),
    )
    with respx.mock:
        respx.get(GH).respond(200, json=jobs)
        respx.get(LV).respond(200, json=[])
        for n in range(2):
            await go(tmp_path, now=T0 + timedelta(minutes=10 * n), sender=owner, channel=channel)
    assert len(channel.sent) == 1 and "Software Engineer Intern" in channel.sent[0]
    assert all("acme-careers.example" not in text for text in channel.sent)
    held = [text for text in owner.sent if "held for review" in text]
    assert len(held) == 1 and "acme-careers.example" in held[0]  # once, not every run
    by_id = {li.external_id: li for li in load_listings(tmp_path / "listings.json")}
    assert by_id["2"].notified is False  # released once its host is approved

    (tmp_path / "companies.yaml").write_text(
        "companies:\n"
        "  - {name: Acme, slug: acme, tier: 1, ats: greenhouse,"
        " ats_config: {board_token: acme}, enabled: true}\n",
        encoding="utf-8",
    )
    readme = tmp_path / "README.md"
    readme.write_text("<!-- LISTINGS:START -->\n<!-- LISTINGS:END -->\n", encoding="utf-8")
    generate(tmp_path, tmp_path, now=T0)
    text = readme.read_text(encoding="utf-8")
    assert "Software Engineer Intern" in text and "acme-careers.example" not in text


# --- floods and the kill switch ---


async def test_channel_daily_cap_sends_the_overflow_to_the_owner(tmp_path, monkeypatch):
    from tracker import main as main_module

    monkeypatch.setattr(main_module, "CHANNEL_DAILY_CAP", 2)
    old_health(tmp_path)
    owner, channel = FakeSender(), FakeSender()
    jobs = gh(
        *[
            (n, f"Software Engineer Intern {n}", f"https://job-boards.greenhouse.io/acme/jobs/{n}")
            for n in range(1, 5)
        ]
    )
    with respx.mock:
        respx.get(GH).respond(200, json=jobs)
        respx.get(LV).respond(200, json=[])
        await go(tmp_path, sender=owner, channel=channel)
    assert sum(text.count("Software Engineer Intern") for text in channel.sent) == 2
    assert sum(text.count("Software Engineer Intern") for text in owner.sent) == 2
    assert all(li.notified for li in load_listings(tmp_path / "listings.json"))


async def test_kill_switch_turns_the_channel_off():
    async with make_client(delay=0, backoff=0) as client:
        env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHANNEL_ID": "@c"}
        assert Telegram.channel_from_env(client, env) is not None
        for value in ("true", "TRUE", "1", "yes"):
            assert Telegram.channel_from_env(client, {**env, "CHANNEL_PAUSED": value}) is None
        assert Telegram.channel_from_env(client, {**env, "CHANNEL_PAUSED": "false"}) is not None


# --- hostile text ---

HOSTILE = [
    "Intern | x | <script>alert(1)</script>",
    "Intern [click](https://evil.com) ![img](https://evil.com/a.png)",
    "Intern <!-- LISTINGS:END --> injected",
    "Intern \u202ereversed\u200b zero-width",
    "Intern *bold* _it_ `code` \\ backslash",
]


@pytest.mark.parametrize("title", HOSTILE)
def test_hostile_titles_cannot_inject_markdown_html_or_end_the_section(title):
    from tests.test_readme import NOW, listing

    text = render_listings([listing(1, title=title)], NOW)
    row = next(line for line in text.splitlines() if line.startswith("| Acme"))
    assert row.count("|") - row.count("\\|") == 9  # still exactly 8 columns
    assert "<script" not in text and "<!--" not in text
    assert "[click](" not in text and "![img](" not in text  # no live markdown link or image


def test_telegram_messages_are_plain_text_never_parsed():
    from tests.test_readme import listing

    message = format_listing(listing(1, title="<b>x</b> [a](https://evil.com)"))
    assert "<b>x</b>" in message  # shown literally; Telegram only parses with parse_mode


async def test_telegram_body_has_no_parse_mode():
    with respx.mock:
        route = respx.post(url__regex=r"https://api\.telegram\.org/bot.*/sendMessage").respond(
            200, json={"ok": True}
        )
        async with make_client(delay=0, backoff=0) as client:
            await Telegram(client, "TOKEN", "1").send("<b>hi</b>")
    assert "parse_mode" not in json.loads(route.calls.last.request.content)


def test_enrichment_never_publishes_contacts_or_links():
    text = (
        "Stipend: contact hr@scam.in or WhatsApp +91 98765 43210, apply at scam.com. "
        "Degree: B.Tech. Stipend: INR 50,000 per month."
    )
    for value in ("contact hr@scam.in", "WhatsApp +91 98765 43210", "apply at scam.com"):
        assert "stipend" not in validate(Extraction(stipend=value), text)
    assert validate(Extraction(stipend="INR 50,000 per month"), text)["stipend"]


# --- secrets and oversized responses ---


async def test_bot_token_never_appears_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    with respx.mock:
        respx.post(url__regex=r"https://api\.telegram\.org/.*").mock(
            side_effect=httpx.ConnectError("boom")
        )
        async with make_client(delay=0, backoff=0) as client:
            assert await Telegram(client, "SECRET-TOKEN-123", "1").send("hi") is False
    assert "SECRET-TOKEN-123" not in caplog.text


async def test_oversized_responses_are_refused_streamed_or_not():
    async def chunks():
        for _ in range(10):
            yield b"x" * 50

    with respx.mock:
        respx.get("https://site.test/stream").respond(200, stream=chunks())
        respx.get("https://site.test/big").respond(200, content=b"x" * 500)
        respx.get("https://site.test/ok").respond(200, json={"a": 1})
        transport = PoliteTransport(delay=0, backoff=0, max_bytes=100)
        async with httpx.AsyncClient(transport=transport) as client:
            assert (await client.get("https://site.test/ok")).json() == {"a": 1}
            for path in ("stream", "big"):
                with pytest.raises(ResponseTooLarge):
                    await client.get(f"https://site.test/{path}")


async def test_postings_with_a_url_in_the_title_or_location_are_dropped(tmp_path):
    old_health(tmp_path)
    jobs = {
        "jobs": [
            {
                "id": 1,
                "title": "Intern - apply at https://evil.com now",
                "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
                "location": {"name": "Pune"},
            },
            {
                "id": 2,
                "title": "Software Engineer Intern",
                "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/2",
                "location": {"name": "Pune www.evil.com"},
            },
        ]
    }
    with respx.mock:
        respx.get(GH).respond(200, json=jobs)
        respx.get(LV).respond(200, json=[])
        await go(tmp_path)
    assert load_listings(tmp_path / "listings.json") == []
