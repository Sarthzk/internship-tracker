import logging
from datetime import UTC, datetime

import httpx
import respx

from tracker.http import make_client
from tracker.models import HealthRecord, Listing
from tracker.notify import (
    CALLMEBOT_URL,
    COMBINE_AT,
    Alert,
    CallMeBot,
    deliver,
    deliver_health_alerts,
    format_listing,
    format_tracking_started,
    plan_alerts,
    plan_health_alerts,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
KEY = "s3cr3t-key-123"


class FakeSender:
    def __init__(self, fail_from: int | None = None) -> None:
        self.sent: list[str] = []
        self.fail_from = fail_from

    async def send(self, text: str) -> bool:
        if self.fail_from is not None and len(self.sent) >= self.fail_from:
            return False
        self.sent.append(text)
        return True


def listing(n: int = 1, company: str = "Acme", **overrides) -> Listing:
    data = {
        "id": f"lever:acme:{n}",
        "company": company,
        "company_slug": "acme",
        "title": f"Software Engineer Intern {n}",
        "category": "swe",
        "locations": ["Bengaluru", "Pune"],
        "is_remote": False,
        "url": f"https://example.com/{n}",
        "source": "lever",
        "external_id": str(n),
        "first_seen": NOW,
        "last_seen": NOW.date(),
    }
    data.update(overrides)
    return Listing.model_validate(data)


# --- message planning ---


def test_format_listing():
    text = format_listing(listing())
    assert "Acme: Software Engineer Intern 1" in text
    assert "Bengaluru; Pune" in text and "https://example.com/1" in text


def test_few_listings_get_one_message_each():
    alerts = plan_alerts([listing(i) for i in range(1, COMBINE_AT)])
    assert len(alerts) == COMBINE_AT - 1
    assert all(len(a.ids) == 1 for a in alerts)


def test_many_listings_are_combined():
    alerts = plan_alerts([listing(i) for i in range(1, COMBINE_AT + 1)])
    assert len(alerts) == 1 and len(alerts[0].ids) == COMBINE_AT
    assert f"{COMBINE_AT} new internships" in alerts[0].text


def test_combined_messages_are_split_to_fit():
    many = [listing(i, title="T" * 140) for i in range(1, 31)]
    alerts = plan_alerts(many)
    assert len(alerts) > 1
    assert all(len(a.text) < 2000 for a in alerts)
    assert sorted(i for a in alerts for i in a.ids) == sorted(li.id for li in many)
    assert f"(1/{len(alerts)})" in alerts[0].text


def test_no_listings_no_alerts():
    assert plan_alerts([]) == []


def test_tracking_started_summary():
    text = format_tracking_started({"Stripe": 1, "Rubrik": 2})
    assert "2 companies" in text and "3 India tech internships" in text
    assert "Rubrik (2), Stripe (1)" in text


# --- delivery ---


async def test_deliver_returns_ids_of_sent_alerts():
    sender = FakeSender()
    alerts = [Alert("a", ["1"]), Alert("b", ["2", "3"])]
    assert await deliver(sender, alerts, pause=0) == {"1", "2", "3"}
    assert sender.sent == ["a", "b"]


async def test_deliver_stops_at_first_failure():
    sender = FakeSender(fail_from=1)
    alerts = [Alert("a", ["1"]), Alert("b", ["2"]), Alert("c", ["3"])]
    assert await deliver(sender, alerts, pause=0) == {"1"}
    assert sender.sent == ["a"]


# --- health alerts ---

NAMES = {"acme": "Acme"}


def test_failure_alert_after_three_failures_only_once():
    health = {"acme": HealthRecord(company_slug="acme", consecutive_failures=2)}
    assert plan_health_alerts(health, NAMES) == []
    health["acme"].consecutive_failures = 3
    health["acme"].last_error = "HTTP 500"
    [alert] = plan_health_alerts(health, NAMES)
    assert alert.alerted is True and "Acme" in alert.text and "HTTP 500" in alert.text
    health["acme"].failure_alerted = True
    health["acme"].consecutive_failures = 4
    assert plan_health_alerts(health, NAMES) == []


def test_recovery_alert_once():
    health = {"acme": HealthRecord(company_slug="acme", failure_alerted=True)}
    [alert] = plan_health_alerts(health, NAMES)
    assert alert.alerted is False and "working again" in alert.text
    health["acme"].failure_alerted = False
    assert plan_health_alerts(health, NAMES) == []


def test_healthy_company_and_unlisted_company_get_no_alerts():
    health = {
        "acme": HealthRecord(company_slug="acme"),
        "gone": HealthRecord(company_slug="gone", consecutive_failures=9),
    }
    assert plan_health_alerts(health, NAMES) == []


async def test_flag_only_set_when_alert_was_delivered():
    health = {"acme": HealthRecord(company_slug="acme", consecutive_failures=3)}
    alerts = plan_health_alerts(health, NAMES)
    await deliver_health_alerts(FakeSender(fail_from=0), alerts, health, pause=0)
    assert health["acme"].failure_alerted is False
    await deliver_health_alerts(FakeSender(), alerts, health, pause=0)
    assert health["acme"].failure_alerted is True


# --- CallMeBot client ---


async def test_callmebot_sends_phone_text_and_key():
    with respx.mock:
        route = respx.get(CALLMEBOT_URL).respond(200, text="<b>Message queued.</b>")
        async with make_client(delay=0, backoff=0) as client:
            ok = await CallMeBot(client, "+919876543210", KEY).send("hello & welcome")
    assert ok is True
    params = route.calls.last.request.url.params
    assert params["phone"] == "+919876543210" and params["text"] == "hello & welcome"
    assert params["apikey"] == KEY


async def test_callmebot_error_body_counts_as_failure():
    with respx.mock:
        respx.get(CALLMEBOT_URL).respond(200, text="ERROR: APIKey is invalid")
        async with make_client(delay=0, backoff=0) as client:
            assert await CallMeBot(client, "+91", KEY).send("x") is False


async def test_callmebot_http_error_and_network_error_are_failures():
    with respx.mock:
        respx.get(CALLMEBOT_URL).respond(503)
        async with make_client(delay=0, backoff=0) as client:
            assert await CallMeBot(client, "+91", KEY).send("x") is False
    with respx.mock:
        respx.get(CALLMEBOT_URL).mock(side_effect=httpx.ConnectError("boom"))
        async with make_client(delay=0, backoff=0) as client:
            assert await CallMeBot(client, "+91", KEY).send("x") is False


async def test_api_key_never_appears_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    with respx.mock:
        respx.get(CALLMEBOT_URL).respond(503)
        async with make_client(delay=0, backoff=0) as client:
            await CallMeBot(client, "+919876543210", KEY).send("x")
    with respx.mock:
        respx.get(CALLMEBOT_URL).mock(side_effect=httpx.ConnectError("boom"))
        async with make_client(delay=0, backoff=0) as client:
            await CallMeBot(client, "+919876543210", KEY).send("x")
    assert KEY not in caplog.text and "919876543210" not in caplog.text


async def test_from_env_skips_with_warning_when_secrets_missing(caplog):
    async with make_client() as client:
        assert CallMeBot.from_env(client, {}) is None
        assert CallMeBot.from_env(client, {"CALLMEBOT_PHONE": "+91"}) is None
        assert CallMeBot.from_env(client, {"CALLMEBOT_PHONE": "+91", "CALLMEBOT_APIKEY": "k"})
    assert "WhatsApp alerts are skipped" in caplog.text
