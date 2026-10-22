from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from scripts import fingerprint_platforms as fp
from scripts.detect_ats import USER_AGENT
from scripts.fingerprint_platforms import (
    CompanyResult,
    Page,
    PoliteClient,
    Signal,
    classify_empty_page,
    collect_urls,
    extract_signals,
    fetch_page,
    fingerprint_company,
    render_report,
    run,
)
from tracker.models import Company

FIXTURES = Path(__file__).parent / "fixtures" / "fingerprint"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def company(name="Acme", slug="acme", url: str | None = "https://acme.example/careers") -> Company:
    return Company(name=name, slug=slug, tier=1, ats="unknown", careers_url=url)


def by_platform(signals: list[Signal], platform: str) -> list[Signal]:
    return [s for s in signals if s.platform == platform]


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    monkeypatch.setattr("scripts.fingerprint_platforms.asyncio.sleep", no_sleep)


@pytest.fixture
async def pc():
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, max_redirects=5
    ) as client:
        yield PoliteClient(client, delay=0)


# --- signature extraction ---


def test_collect_urls_unescapes_json_and_protocol_relative():
    urls = collect_urls(r'{"u":"https:\/\/a.example.com\/x"} <script src="//cdn.example.org/a.js">')
    assert "https://a.example.com/x" in urls
    assert "https://cdn.example.org/a.js" in urls


def test_workday_extracts_host_tenant_site_and_skips_locale():
    signals = extract_signals("https://acme.example/careers", [], html("workday.html"))
    configs = [s.config for s in by_platform(signals, "workday")]
    assert configs == [
        {"host": "acme.wd5.myworkdayjobs.com", "tenant": "acme", "site": "AcmeCareers"}
    ]


def test_workday_cxs_url_is_authoritative_for_tenant_and_site():
    signals = extract_signals("https://x.example", [], html("workday_cxs.html"))
    assert by_platform(signals, "workday")[0].config == {
        "host": "globex.wd1.myworkdayjobs.com",
        "tenant": "globex",
        "site": "GlobexJobs",
    }


def test_workday_bare_host_has_no_site():
    signals = extract_signals("https://x.example", [], html("workday_bare.html"))
    assert by_platform(signals, "workday")[0].config == {
        "host": "initech.wd3.myworkdayjobs.com",
        "tenant": "initech",
    }


def test_eightfold_host_from_link():
    signals = extract_signals("https://x.example", [], html("eightfold_link.html"))
    assert by_platform(signals, "eightfold")[0].config == {"host": "acme.eightfold.ai"}


def test_eightfold_pcsx_mention_uses_page_host():
    signals = extract_signals("https://careers.example.com/home", [], html("eightfold_pcsx.html"))
    found = by_platform(signals, "eightfold")
    assert [(s.config, s.rank) for s in found] == [({"host": "careers.example.com"}, 1)]


def test_pcsx_inside_a_longer_word_is_ignored():
    assert extract_signals("https://x.example", [], "<p>abcpcsxdef</p>") == []


def test_oracle_hcm_host_and_site_with_and_without_locale():
    signals = by_platform(
        extract_signals("https://x.example", [], html("oracle_hcm.html")), "oracle_hcm"
    )
    assert sorted(s.config["host"] for s in signals) == [
        "example.fa.us2.oraclecloud.com",
        "other.fa.em2.oraclecloud.com",
    ]
    assert {s.config["site"] for s in signals} == {"CX_1001", "CX_2"}


def test_phenom_detected_from_cdn_with_page_host():
    signals = extract_signals("https://careers.example.com", [], html("phenom.html"))
    assert [(s.platform, s.config, s.rank) for s in signals] == [
        ("phenom", {"host": "careers.example.com"}, 2)
    ]


def test_greenhouse_variants_and_reserved_paths():
    signals = extract_signals("https://x.example", [], html("greenhouse.html"))
    tokens = sorted(s.config["board_token"] for s in by_platform(signals, "greenhouse"))
    assert tokens == ["acme", "acme2", "acme3", "acme4", "acme5"]


def test_lever_ashby_smartrecruiters_and_unsupported_platforms():
    signals = extract_signals("https://x.example", [], html("other_ats.html"))
    assert by_platform(signals, "lever")[0].config == {"site": "leverco"}
    assert by_platform(signals, "ashby")[0].config == {"site": "ashbyco"}
    sr = sorted(s.config["company_id"] for s in by_platform(signals, "smartrecruiters"))
    assert sr == ["OneClickCo", "SmartCo"]
    other = {s.platform for s in signals if s.platform.startswith("other:")}
    assert other == {"other:icims", "other:taleo", "other:workable"}


def test_redirect_chain_outranks_html_links():
    chain = ["https://careers.example.com/", "https://acme.wd5.myworkdayjobs.com/en-US/Ext"]
    signals = extract_signals(
        "https://acme.wd5.myworkdayjobs.com/en-US/Ext", chain, html("workday.html")
    )
    workday = by_platform(signals, "workday")
    assert signals[0].rank == 3
    assert workday[0].config["site"] == "Ext"
    assert {s.config["site"] for s in workday} == {"Ext", "AcmeCareers"}


def test_no_signals_in_plain_page():
    assert extract_signals("https://x.example", [], html("static_nosignal.html")) == []


def test_classify_js_shell_vs_static_page():
    assert classify_empty_page(html("js_shell.html")) == "js-rendered"
    assert classify_empty_page(html("static_nosignal.html")) == "no-signal"


# --- polite client ---


@respx.mock
async def test_polite_client_retries_503_then_succeeds(pc):
    route = respx.get("https://a.example/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, text="ok")]
    )
    assert (await pc.request("GET", "https://a.example/x")).text == "ok"
    assert route.call_count == 2


@respx.mock
async def test_polite_client_does_not_retry_404(pc):
    route = respx.get("https://a.example/x").mock(return_value=httpx.Response(404))
    assert (await pc.request("GET", "https://a.example/x")).status_code == 404
    assert route.call_count == 1


@respx.mock
async def test_polite_client_gives_up_after_three_attempts(pc):
    route = respx.get("https://a.example/x").mock(return_value=httpx.Response(429))
    assert (await pc.request("GET", "https://a.example/x")).status_code == 429
    assert route.call_count == 3


@respx.mock
async def test_polite_client_retries_network_errors_then_raises(pc):
    route = respx.get("https://a.example/x").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(httpx.ConnectError):
        await pc.request("GET", "https://a.example/x")
    assert route.call_count == 3


@respx.mock
async def test_polite_client_waits_between_requests_to_same_host_only(monkeypatch):
    sleeps: list[float] = []

    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("scripts.fingerprint_platforms.asyncio.sleep", record)
    respx.route().mock(return_value=httpx.Response(200, json={}))
    async with httpx.AsyncClient() as client:
        polite = PoliteClient(client, delay=1.0)
        await polite.request("GET", "https://a.example/1")
        await polite.request("GET", "https://b.example/1")
        assert sleeps == []
        await polite.request("GET", "https://a.example/2")
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 1.0


@respx.mock
async def test_requests_carry_the_project_user_agent(pc):
    route = respx.get("https://a.example/x").mock(return_value=httpx.Response(200))
    await pc.request("GET", "https://a.example/x")
    assert route.calls[0].request.headers["User-Agent"] == USER_AGENT
    assert "internship-tracker/" in USER_AGENT


# --- page fetching ---


@respx.mock
async def test_fetch_page_records_redirect_chain(pc):
    respx.get("https://old.example/careers").mock(
        return_value=httpx.Response(301, headers={"Location": "https://new.example/jobs"})
    )
    respx.get("https://new.example/jobs").mock(return_value=httpx.Response(200, text="<p>hi</p>"))
    page = await fetch_page(pc, "https://old.example/careers")
    assert page.status == "ok"
    assert page.final_url == "https://new.example/jobs"
    assert page.chain == ["https://old.example/careers"]


@respx.mock
@pytest.mark.parametrize(
    "status,expected",
    [
        (403, "blocked"),
        (429, "blocked"),
        (404, "not-found"),
        (410, "not-found"),
        (418, "http-error"),
    ],
)
async def test_fetch_page_statuses(pc, status, expected):
    respx.get("https://a.example/careers").mock(return_value=httpx.Response(status))
    assert (await fetch_page(pc, "https://a.example/careers")).status == expected


@respx.mock
async def test_fetch_page_network_error_and_missing_url(pc):
    respx.get("https://a.example/careers").mock(side_effect=httpx.ConnectError("down"))
    assert (await fetch_page(pc, "https://a.example/careers")).status == "error"
    assert (await fetch_page(pc, None)).status == "no-careers-url"


@respx.mock
async def test_fetch_page_too_many_redirects(pc):
    respx.get("https://a.example/loop").mock(
        return_value=httpx.Response(302, headers={"Location": "https://a.example/loop"})
    )
    assert (await fetch_page(pc, "https://a.example/loop")).status == "error"


# --- verification, end to end per company ---

GH_JOBS = {
    "jobs": [
        {"location": {"name": "Bengaluru, India"}, "company_name": "Acme"},
        {"location": {"name": "Dublin"}, "company_name": "Acme"},
    ]
}
CAREERS = "https://acme.example/careers"


def page_with(body: str):
    respx.get(CAREERS).mock(return_value=httpx.Response(200, text=body))


@respx.mock
async def test_greenhouse_hit_is_verified_with_counts(pc):
    page_with('<a href="https://boards.greenhouse.io/acme">jobs</a>')
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json=GH_JOBS)
    )
    result = await fingerprint_company(pc, company())
    assert result.outcome == "greenhouse" and result.verified
    assert (result.verification.total, result.verification.india) == (2, 1)
    assert result.verification.config == {"board_token": "acme"}


@respx.mock
async def test_empty_board_is_not_verified(pc):
    page_with('<a href="https://boards.greenhouse.io/acme">jobs</a>')
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json={"jobs": []})
    )
    result = await fingerprint_company(pc, company())
    assert result.outcome == "greenhouse" and not result.verified
    assert "0 jobs" in " ".join(result.notes)


@respx.mock
async def test_404_board_is_not_verified(pc):
    page_with('<a href="https://jobs.lever.co/acme">jobs</a>')
    respx.get("https://api.lever.co/v0/postings/acme").mock(return_value=httpx.Response(404))
    result = await fingerprint_company(pc, company())
    assert result.outcome == "lever" and not result.verified


@respx.mock
async def test_smartrecruiters_requires_matching_company_name(pc):
    page_with('<a href="https://jobs.smartrecruiters.com/acme">jobs</a>')
    content = [{"location": {"country": "in"}, "company": {"name": "Somebody Else"}}]
    respx.get(url__regex=r"https://api\.smartrecruiters\.com/v1/companies/acme/postings.*").mock(
        return_value=httpx.Response(200, json={"totalFound": 1, "content": content})
    )
    result = await fingerprint_company(pc, company())
    assert not result.verified
    assert "mismatch" in " ".join(result.notes)


@respx.mock
async def test_workday_verified_and_india_sampled_across_pages(pc):
    page_with('<a href="https://acme.wd5.myworkdayjobs.com/en-US/Ext">jobs</a>')

    def postings(*locs):
        return [{"title": "x", "locationsText": loc} for loc in locs]

    route = respx.post("https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Ext/jobs").mock(
        side_effect=[
            httpx.Response(
                200, json={"total": 3, "jobPostings": postings("Pune, India", "Dublin")}
            ),
            httpx.Response(200, json={"total": 0, "jobPostings": postings("Bengaluru")}),
        ]
    )
    result = await fingerprint_company(pc, company())
    assert result.outcome == "workday" and result.verified
    assert (result.verification.total, result.verification.india) == (3, 2)
    assert result.verification.config == {
        "host": "acme.wd5.myworkdayjobs.com",
        "tenant": "acme",
        "site": "Ext",
    }
    assert route.calls[0].request.content == (
        b'{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}'
    )


@respx.mock
async def test_workday_without_site_is_unverified_and_makes_no_api_call(pc):
    page_with('<a href="https://initech.wd3.myworkdayjobs.com/">jobs</a>')
    result = await fingerprint_company(pc, company())
    assert result.outcome == "workday" and not result.verified
    assert "site" in " ".join(result.notes)


@respx.mock
async def test_eightfold_tries_domain_candidates_until_one_works(pc):
    page_with('<a href="https://acme.eightfold.ai/careers?domain=wrong.com">jobs</a>')
    good = {"data": {"count": 40, "positions": [{"id": 1}]}}
    india = {"data": {"count": 7, "positions": [{"id": 1}]}}

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params["domain"] != "acme.com":
            return httpx.Response(200, json={"data": {"count": 0, "positions": []}})
        return httpx.Response(200, json=india if params.get("location") == "India" else good)

    respx.get(url__regex=r"https://acme\.eightfold\.ai/api/pcsx/search.*").mock(side_effect=handler)
    result = await fingerprint_company(pc, company(url=CAREERS))
    assert result.outcome == "eightfold" and result.verified
    assert (result.verification.total, result.verification.india) == (40, 7)
    assert result.verification.config == {"host": "acme.eightfold.ai", "domain": "acme.com"}


@respx.mock
async def test_eightfold_no_domain_works(pc):
    page_with('<a href="https://acme.eightfold.ai/careers">jobs</a>')
    respx.get(url__regex=r"https://acme\.eightfold\.ai/api/pcsx/search.*").mock(
        return_value=httpx.Response(404)
    )
    result = await fingerprint_company(pc, company())
    assert not result.verified
    assert "no domain worked" in " ".join(result.notes)


@respx.mock
async def test_oracle_hcm_verified_with_sampled_india_count(pc):
    page_with(
        '<a href="https://jp.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs">x</a>'
    )
    reqs = [
        {"Id": "1", "PrimaryLocationCountry": "IN", "PrimaryLocation": "Mumbai, India"},
        {"Id": "2", "PrimaryLocationCountry": "US", "PrimaryLocation": "Plano, TX"},
    ]
    route = respx.get(url__startswith="https://jp.fa.oraclecloud.com/hcmRestApi/").mock(
        return_value=httpx.Response(
            200, json={"items": [{"TotalJobsCount": 2, "requisitionList": reqs}]}
        )
    )
    result = await fingerprint_company(pc, company())
    assert result.outcome == "oracle_hcm" and result.verified
    assert (result.verification.total, result.verification.india) == (2, 1)
    assert not result.verification.partial
    assert "siteNumber=CX_1" in str(route.calls[0].request.url)
    assert route.calls[0].request.headers["Accept"] == "application/json"


@respx.mock
async def test_oracle_hcm_bad_shape_is_unverified(pc):
    page_with(
        '<a href="https://jp.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs">x</a>'
    )
    respx.get(url__startswith="https://jp.fa.oraclecloud.com/hcmRestApi/").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    assert not (await fingerprint_company(pc, company())).verified


@respx.mock
async def test_first_failing_guess_falls_through_to_next_candidate(pc):
    page_with(
        '<a href="https://boards.greenhouse.io/acme">gh</a><a href="https://jobs.lever.co/acme">l</a>'
    )
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://api.lever.co/v0/postings/acme").mock(
        return_value=httpx.Response(200, json=[{"categories": {"location": "Pune"}}])
    )
    result = await fingerprint_company(pc, company())
    assert result.outcome == "lever" and result.verified
    assert any("greenhouse" in n for n in result.notes)


@respx.mock
async def test_detect_only_and_unsupported_platforms_make_no_api_calls(pc):
    page_with('<a href="https://careers-acme.icims.com/jobs">x</a>')
    result = await fingerprint_company(pc, company())
    assert result.outcome == "other:icims" and not result.verified
    assert result.verification is None
    assert len(respx.calls) == 1  # only the careers page


@respx.mock
async def test_phenom_is_detected_but_not_verified(pc):
    page_with(html("phenom.html"))
    result = await fingerprint_company(pc, company())
    assert result.outcome == "phenom" and result.verification is None


@respx.mock
async def test_js_rendered_page_is_recorded_not_guessed(pc):
    page_with(html("js_shell.html"))
    result = await fingerprint_company(pc, company())
    assert result.outcome == "js-rendered" and result.chosen is None
    assert len(respx.calls) == 1


@respx.mock
async def test_blocked_page(pc):
    respx.get(CAREERS).mock(return_value=httpx.Response(403))
    assert (await fingerprint_company(pc, company())).outcome == "blocked"


@respx.mock
async def test_one_company_failing_does_not_crash_the_run(pc, monkeypatch):
    real = fingerprint_company

    async def flaky(client, comp):
        if comp.slug == "bad":
            raise RuntimeError("kaboom")
        return await real(client, comp)

    monkeypatch.setattr(fp, "fingerprint_company", flaky)
    respx.get(CAREERS).mock(return_value=httpx.Response(200, text=html("js_shell.html")))
    results = await run(pc, [company("Bad", "bad"), company()])
    assert [r.outcome for r in results] == ["error", "js-rendered"]
    assert "kaboom" in results[0].notes[0]


# --- report ---


def make_result(name, slug, outcome, verified=False, **kw) -> CompanyResult:
    comp = company(name, slug, kw.pop("url", f"https://{slug}.example/careers"))
    verification = None
    chosen = None
    if outcome in fp.VERIFIABLE:
        chosen = Signal(outcome, {"site": slug}, f"https://x/{slug}", 3)
        verification = fp.Verification(
            verified, 10 if verified else None, 4 if verified else None, kw.pop("partial", False),
            config={"site": slug},
        )  # fmt: skip
    return CompanyResult(
        comp,
        Page("ok", 200, kw.pop("final_url", comp.careers_url)),
        outcome,
        chosen=chosen,
        verification=verification,
        notes=kw.pop("notes", []),
    )


def test_report_covers_every_company_with_summary_counts():
    results = [
        make_result("A", "a", "lever", True),
        make_result("B", "b", "lever", True, partial=True),
        make_result("C", "c", "greenhouse", False, notes=["greenhouse: board has 0 jobs"]),
        make_result("D", "d", "js-rendered"),
        make_result("E", "e", "blocked", notes=["HTTP 403"]),
        make_result("F", "f", "other:icims"),
    ]
    report = render_report(results, datetime(2026, 10, 22, tzinfo=UTC))
    for name in "ABCDEF":
        assert f"| {name} |" in report
    assert "- Lever: 2 (2 verified, 0 unverified)" in report
    assert "- Greenhouse: 1 (0 verified, 1 unverified)" in report
    assert "- icims (unsupported): 1" in report
    assert "- js-rendered: 1" in report and "- blocked: 1" in report
    assert "6 companies covered" in report


def test_report_only_suggests_verified_guesses_for_yaml():
    results = [
        make_result("A", "a", "lever", True),
        make_result("C", "c", "greenhouse", False),
    ]
    section = render_report(results).split("## Suggested companies.yaml updates")[1].split("##")[0]
    assert "A (`a`): `ats: lever, ats_config: {site: a}`" in section
    assert "(`c`)" not in section


def test_report_marks_unverified_and_partial_counts_and_escapes_pipes():
    results = [
        make_result("A", "a", "lever", True, partial=True),
        make_result("C", "c", "greenhouse", False, notes=["a|b"]),
    ]
    report = render_report(results)
    assert "≥4" in report
    assert "⚠️ unverified guess" in report
    assert "a\\|b" in report


def test_report_suggests_careers_url_changes_for_redirects():
    results = [
        make_result("A", "a", "lever", True, final_url="https://new.example/jobs"),
        make_result("B", "b", "lever", True, final_url="https://b.example/careers/"),
    ]
    section = render_report(results).split("## Suggested careers_url changes")[1].split("##")[0]
    assert "A: `https://a.example/careers` → `https://new.example/jobs`" in section
    assert "B:" not in section  # trailing slash only
