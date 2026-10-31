"""Enrichment wired into a run, and the description fetchers (all offline)."""

import json
from datetime import UTC, datetime, timedelta

import respx

from tests.test_enrich import FakeCompleter, reply
from tests.test_main import GH, LV, T0, FakeSender, companies, gh_jobs, old_health
from tracker.descriptions import fetch_description, to_text
from tracker.http import make_client
from tracker.main import run
from tracker.models import Company, Listing
from tracker.storage import load_listings

JOB = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/100"
TEXT = "Open to 2027 graduates. This is a 6-month internship with a stipend of INR 50,000."


def acme() -> Company:
    return companies()[0]


async def go(tmp_path, completer, now=T0, sender=None):
    async with make_client(delay=0, backoff=0) as client:
        return await run(
            companies(),
            client,
            tmp_path,
            now=now,
            sender=sender,
            pause=0,
            enricher=(completer, "m", 40),
        )


async def test_new_listing_is_enriched_before_its_alert_is_sent(tmp_path):
    old_health(tmp_path)
    sender = FakeSender()
    completer = FakeCompleter(reply(eligible_batches=[2027], duration_months=6))
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        respx.get(JOB).respond(200, json={"content": f"&lt;p&gt;{TEXT}&lt;/p&gt;"})
        await go(tmp_path, completer, sender=sender)
    assert "Batch 2027 · 6 months" in sender.sent[0]
    [li] = load_listings(tmp_path / "listings.json")
    assert li.enrichment.eligible_batches == [2027] and li.enrichment.model == "m"
    assert TEXT not in (tmp_path / "listings.json").read_text()  # no description on disk


async def test_enrichment_happens_once_and_quiet_runs_stay_identical(tmp_path):
    old_health(tmp_path)
    completer = FakeCompleter(reply(eligible_batches=[2027]))
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        detail = respx.get(JOB).respond(200, json={"content": TEXT})
        await go(tmp_path, completer)
        before = (tmp_path / "listings.json").read_bytes()
        await go(tmp_path, completer, now=T0 + timedelta(minutes=10))
    assert (tmp_path / "listings.json").read_bytes() == before
    assert len(completer.calls) == 1 and detail.call_count == 1


async def test_description_failure_never_breaks_the_run_and_is_retried(tmp_path):
    old_health(tmp_path)
    completer = FakeCompleter(reply(eligible_batches=[2027]))
    sender = FakeSender()
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        respx.get(JOB).respond(500)
        await go(tmp_path, completer, sender=sender)
        [li] = load_listings(tmp_path / "listings.json")
        assert li.enrichment is None and len(sender.sent) == 1 and "🎓" not in sender.sent[0]
        respx.get(JOB).respond(200, json={"content": TEXT})
        await go(tmp_path, completer, now=T0 + timedelta(minutes=10))
    [li] = load_listings(tmp_path / "listings.json")
    assert li.enrichment.eligible_batches == [2027]


async def test_dry_run_and_missing_key_skip_enrichment(tmp_path):
    completer = FakeCompleter(reply())
    with respx.mock:
        respx.get(GH).respond(200, json=gh_jobs(("Software Engineer Intern", "Pune")))
        respx.get(LV).respond(200, json=[])
        async with make_client(delay=0, backoff=0) as client:
            await run(
                companies(), client, tmp_path, now=T0, dry_run=True, enricher=(completer, "m", 40)
            )
            await run(companies(), client, tmp_path, now=T0, enricher=None)
    assert completer.calls == []
    [li] = load_listings(tmp_path / "listings.json")
    assert li.enrichment is None


def listing_for(source: str, external_id: str, url: str) -> Listing:
    now = datetime(2026, 10, 31, tzinfo=UTC)
    return Listing(
        id=f"{source}:x:{external_id}", company="X", company_slug="x", title="Intern",
        category="swe", locations=["Pune"], is_remote=False, url=url, source=source,
        external_id=external_id, first_seen=now, last_seen=now.date(),
    )  # fmt: skip


def company(ats: str, **config) -> Company:
    return Company(name="X", slug="x", tier=1, ats=ats, ats_config=config, enabled=True)


async def test_workday_description_comes_from_the_matching_api_path():
    cfg = {"host": "x.wd1.myworkdayjobs.com", "tenant": "x", "site": "Careers"}
    li = listing_for("workday", "R1", "https://x.wd1.myworkdayjobs.com/Careers/job/Pune/Intern_R1")
    api = "https://x.wd1.myworkdayjobs.com/wday/cxs/x/Careers/job/Pune/Intern_R1"
    with respx.mock:
        respx.get(api).respond(200, json={"jobPostingInfo": {"jobDescription": "<p>Hi 2027</p>"}})
        async with make_client(delay=0, backoff=0) as client:
            assert await fetch_description(li, company("workday", **cfg), client) == "Hi 2027"


async def test_smartrecruiters_and_oracle_and_eightfold_descriptions():
    async with make_client(delay=0, backoff=0) as client, respx.mock:
        respx.get("https://api.smartrecruiters.com/v1/companies/X/postings/9").respond(
            200,
            json={"jobAd": {"sections": {
                "companyDescription": {"text": "about us"},
                "jobDescription": {"text": "<b>Build</b> things"},
            }}},
        )  # fmt: skip
        sr = await fetch_description(
            listing_for("smartrecruiters", "9", "https://j/9"),
            company("smartrecruiters", company_id="X"),
            client,
        )
        assert sr == "Build things"
        respx.get(
            "https://h.example/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
        ).respond(200, json={"items": [{"ExternalDescriptionStr": "<p>Oracle text</p>"}]})
        oracle = await fetch_description(
            listing_for("oracle_hcm", "5", "https://j/5"),
            company("oracle_hcm", host="h.example", site="CX_1"),
            client,
        )
        assert oracle == "Oracle text"
        respx.get("https://e.example/api/apply/v2/jobs/7").respond(
            200, json={"job_description": "Eight fold"}
        )
        ef = await fetch_description(
            listing_for("eightfold", "7", "https://j/7"),
            company("eightfold", host="e.example", domain="x.com"),
            client,
        )
        assert ef == "Eight fold"


async def test_unsupported_source_or_error_gives_none():
    async with make_client(delay=0, backoff=0) as client, respx.mock:
        li = listing_for("custom", "1", "https://j/1")
        assert await fetch_description(li, acme(), client) is None
        respx.get(JOB).respond(404)
        gh = listing_for("greenhouse", "100", "https://j/100")
        assert (
            await fetch_description(gh, company("greenhouse", board_token="acme"), client) is None
        )


def test_to_text_strips_markup_even_when_escaped_twice():
    assert (
        to_text("&lt;p&gt;Hello&amp;nbsp;<b>world</b>&lt;/p&gt;<script>x()</script>")
        == "Hello world"
    )
    assert to_text(None) == ""
    assert json  # keep import used
