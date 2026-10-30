import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import respx

from tests.test_main import GH, LV, T0, FakeSender, companies, gh_jobs, go, old_health
from tracker import main as main_module
from tracker.http import make_client
from tracker.main import FETCH_TIMEOUT, PreviousRun, _run_cli, fetch_company
from tracker.models import Listing
from tracker.notify import digest_due
from tracker.storage import load_listings, save_listings


def old_listing(n: int) -> Listing:
    return Listing.model_validate(
        {
            "id": f"greenhouse:acme:{n}",
            "company": "Acme",
            "company_slug": "acme",
            "title": f"Software Engineer Intern {n}",
            "category": "swe",
            "locations": ["Pune"],
            "is_remote": False,
            "url": f"https://gh.example/{n}",
            "source": "greenhouse",
            "external_id": str(n),
            "first_seen": T0 - timedelta(days=10),
            "last_seen": T0.date(),
            "notified": True,
        }
    )


# --- A6: per-company time limit ---


async def test_a_stuck_company_fails_alone_after_the_time_limit(monkeypatch):
    async def stuck(company, client):
        await asyncio.sleep(5)

    monkeypatch.setattr(main_module.fetchers, "get_fetcher", lambda company: stuck)
    async with make_client(delay=0, backoff=0) as client:
        outcome = await fetch_company(companies()[0], client, timeout=0.05)
    assert outcome.postings is None and outcome.error.startswith("TimeoutError")
    assert FETCH_TIMEOUT == 120.0


# --- A2: id churn and the message cap ---


async def test_wholesale_id_change_sends_one_admin_message_not_a_flood(tmp_path):
    old_health(tmp_path)
    save_listings(tmp_path / "listings.json", [old_listing(n) for n in range(1, 8)])
    new_jobs = gh_jobs(
        *[(f"Software Engineer Intern X{i}", "Pune") for i in range(6)], first_id=500
    )
    sender = FakeSender()
    with respx.mock:
        respx.get(GH).respond(200, json=new_jobs)
        respx.get(LV).respond(200, json=[])
        await go(tmp_path, sender=sender, pause=0)
    assert len(sender.sent) == 1 and "Possible site change" in sender.sent[0]
    assert "Acme: 6 new while 7 known ones vanished" in sender.sent[0]
    listings = load_listings(tmp_path / "listings.json")
    assert len(listings) == 13 and all(li.notified for li in listings)


async def test_a_genuine_burst_is_still_alerted(tmp_path):
    old_health(tmp_path)
    jobs = gh_jobs(*[(f"Software Engineer Intern X{i}", "Pune") for i in range(12)])
    sender = FakeSender()
    with respx.mock:
        respx.get(GH).respond(200, json=jobs)
        respx.get(LV).respond(200, json=[])
        await go(tmp_path, sender=sender, pause=0)
    assert sender.sent and "Possible site change" not in sender.sent[0]
    assert "12 new internships" in sender.sent[0]


async def test_message_cap_defers_the_rest_to_the_next_run(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "MAX_ALERT_MESSAGES", 2)
    old_health(tmp_path)
    jobs = gh_jobs(*[(f"Software Engineer Intern X{i}", "Pune") for i in range(4)])
    sender = FakeSender()
    with respx.mock:
        respx.get(GH).respond(200, json=jobs)
        respx.get(LV).respond(200, json=[])
        first = await go(tmp_path, sender=sender, pause=0)
        second = await go(tmp_path, now=T0 + timedelta(minutes=10), sender=sender, pause=0)
    assert first.alerts_sent == 2 and first.alerts_pending == 2
    assert second.alerts_sent == 2 and second.alerts_pending == 0
    assert len(sender.sent) == 4


# --- A1: crash alert once, then recovery ---


def fake_environment(monkeypatch, sender, previous, run_result):
    async def fake_previous(client, env=None):
        return previous

    async def fake_run(*args, **kwargs):
        if isinstance(run_result, Exception):
            raise run_result
        return run_result

    monkeypatch.setattr(main_module.Telegram, "from_env", lambda client, env=None: sender)
    monkeypatch.setattr(main_module, "previous_run", fake_previous)
    monkeypatch.setattr(main_module, "run", fake_run)


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "companies.yaml").write_text(
        "companies:\n  - {name: Acme, slug: acme, tier: 1, ats: lever, ats_config: {site: a},"
        " enabled: true}\n",
        encoding="utf-8",
    )
    return tmp_path


def recent(conclusion):
    return PreviousRun(datetime.now(UTC) - timedelta(minutes=10), conclusion)


async def test_first_crash_alerts_and_repeat_crashes_stay_quiet(monkeypatch, data_dir):
    first = FakeSender()
    fake_environment(monkeypatch, first, recent("success"), RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await _run_cli(False, data_dir)
    assert len(first.sent) == 1 and "crashed" in first.sent[0]

    repeat = FakeSender()
    fake_environment(monkeypatch, repeat, recent("failure"), RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        await _run_cli(False, data_dir)
    assert repeat.sent == []


async def test_recovery_message_after_a_failed_run(monkeypatch, data_dir):
    from tracker.main import RunSummary

    sender = FakeSender()
    fake_environment(monkeypatch, sender, recent("failure"), RunSummary())
    assert await _run_cli(False, data_dir) == 0
    assert sender.sent == ["✅ internship-tracker is running normally again."]


async def test_no_recovery_message_when_all_is_well(monkeypatch, data_dir):
    from tracker.main import RunSummary

    sender = FakeSender()
    fake_environment(monkeypatch, sender, recent("success"), RunSummary())
    await _run_cli(False, data_dir)
    assert sender.sent == []


async def test_digest_is_sent_when_due(monkeypatch, data_dir):
    from tracker.main import RunSummary

    sender = FakeSender()
    fake_environment(monkeypatch, sender, recent("success"), RunSummary())
    monkeypatch.setattr(main_module, "digest_due", lambda now, previous_start: True)
    await _run_cli(False, data_dir)
    assert len(sender.sent) == 1 and "Daily report" in sender.sent[0]
    assert "1 of 1 companies OK" in sender.sent[0]


# --- A7: when the digest is due (09:00-09:09 IST = 03:30-03:39 UTC) ---

IST_NINE = datetime(2026, 10, 29, 3, 35, tzinfo=UTC)


def test_digest_due_only_in_the_nine_am_window():
    assert digest_due(IST_NINE, IST_NINE - timedelta(minutes=10))
    assert digest_due(IST_NINE, None)
    assert not digest_due(IST_NINE + timedelta(minutes=10), None)  # 09:15
    assert not digest_due(IST_NINE - timedelta(hours=1), None)  # 08:05


def test_digest_not_repeated_when_the_previous_run_was_in_the_same_window():
    previous = datetime(2026, 10, 29, 3, 31, tzinfo=UTC)  # 09:01 IST, already in the window
    assert not digest_due(IST_NINE, previous)


# --- B2: old closed listings are pruned ---


def test_closed_listings_older_than_180_days_are_dropped():
    from tracker.diff import prune_closed

    def closed_ago(n: int, days: int) -> Listing:
        return old_listing(n).model_copy(
            update={"status": "closed", "closed_at": T0 - timedelta(days=days)}
        )

    kept = prune_closed([old_listing(1), closed_ago(2, 179), closed_ago(3, 181)], T0)
    assert [li.external_id for li in kept] == ["1", "2"]


# --- stale previous-run lookups must not raise false alarms ---


def test_only_the_run_right_before_this_one_is_trusted():
    from tracker.health import is_previous_run

    assert is_previous_run(49, 50)
    assert not is_previous_run(30, 50)  # stale: runs 31-49 are missing from the list
    assert is_previous_run(None, 50) and is_previous_run(49, None)  # unknown (local run)


async def test_stale_lookup_sends_no_gap_alert_and_no_recovery(monkeypatch, data_dir):
    from tracker.main import RunSummary

    sender = FakeSender()
    stale = PreviousRun(datetime.now(UTC) - timedelta(hours=13), "failure", 30)
    fake_environment(monkeypatch, sender, stale, RunSummary())
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "50")
    await _run_cli(False, data_dir)
    assert sender.sent == []
