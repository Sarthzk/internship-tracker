from pathlib import Path

from tracker.fetchers import get_fetcher
from tracker.models import load_companies

COMPANIES_YAML = Path(__file__).resolve().parent.parent / "data" / "companies.yaml"


def test_companies_yaml_loads():
    companies = load_companies(COMPANIES_YAML)
    assert len(companies) >= 50


def test_companies_have_unique_slugs_and_names():
    companies = load_companies(COMPANIES_YAML)
    slugs = [c.slug for c in companies]
    names = [c.name for c in companies]
    assert len(slugs) == len(set(slugs))
    assert len(names) == len(set(names))


def test_every_company_has_a_careers_url():
    for c in load_companies(COMPANIES_YAML):
        assert c.careers_url and c.careers_url.startswith("https://"), c.slug


def test_verified_entries_from_verified_endpoints_doc():
    by_slug = {c.slug: c for c in load_companies(COMPANIES_YAML)}
    assert by_slug["razorpay"].ats == "greenhouse"
    assert by_slug["razorpay"].ats_config == {"board_token": "razorpaysoftwareprivatelimited"}
    assert by_slug["cred"].ats_config == {"site": "cred"}
    assert by_slug["nvidia"].ats_config["tenant"] == "nvidia"
    assert by_slug["microsoft"].ats == "eightfold"
    assert by_slug["jpmorgan-chase"].ats_config == {
        "host": "jpmc.fa.oraclecloud.com",
        "site": "CX_1001",
    }
    assert by_slug["adobe"].ats == "phenom"


def test_custom_companies():
    by_slug = {c.slug: c for c in load_companies(COMPANIES_YAML)}
    for slug in ("amazon", "atlassian", "goldman-sachs"):
        assert by_slug[slug].ats == "custom" and by_slug[slug].enabled
        assert "Custom fetcher" in by_slug[slug].notes
    for slug in ("google", "apple"):
        assert by_slug[slug].ats == "custom" and by_slug[slug].notes


def test_only_companies_with_a_built_fetcher_type_are_enabled():
    # A company is only switched on once its fetcher exists (and passed the cloud check).
    for c in load_companies(COMPANIES_YAML):
        if c.enabled:
            assert get_fetcher(c) is not None, c.slug


def test_unresolved_companies_are_still_listed():
    unresolved = {c.name for c in load_companies(COMPANIES_YAML) if c.ats == "unknown"}
    assert len(unresolved) == 11  # Cohesity resolved to Workday in Phase 10
    assert {"Zomato", "Media.net", "Persistent Systems"} <= unresolved


def test_platform_report_verified_companies():
    by_slug = {c.slug: c for c in load_companies(COMPANIES_YAML)}
    expected = {
        "uber": "oracle_hcm",
        "qualcomm": "eightfold",
        "paypal": "eightfold",
        "morgan-stanley": "eightfold",
        "intel": "workday",
        "visa": "workday",
        "mastercard": "workday",
        "browserstack": "workday",
        "sprinklr": "workday",
    }
    for slug, ats in expected.items():
        assert by_slug[slug].ats == ats, slug
        if get_fetcher(by_slug[slug]) is None:
            assert not by_slug[slug].enabled, slug


def test_removed_companies_are_gone():
    slugs = {c.slug for c in load_companies(COMPANIES_YAML)}
    assert not {"dream11", "sharechat"} & slugs


def test_every_enabled_company_has_a_tag():
    missing = [c.slug for c in load_companies(COMPANIES_YAML) if c.enabled and not c.tag]
    assert not missing, missing


def test_no_ten_minute_run_queues_too_many_companies_on_one_platform():
    """All due companies start together and share one request slot per host, so a run where
    too many are due at once could push the last ones past the per-company timeout."""
    from collections import Counter
    from datetime import UTC, datetime, timedelta

    from tracker.schedule import is_due

    enabled = [c for c in load_companies(COMPANIES_YAML) if c.enabled]
    start = datetime(2026, 11, 3, tzinfo=UTC)
    worst = 0
    for slot in range(144):  # every 10-minute slot of a day
        now = start + timedelta(minutes=10 * slot)
        per_platform = Counter(c.ats for c in enabled if is_due(c, now))
        worst = max(worst, max(per_platform.values()))
    assert worst <= 60, worst


def test_phase_10_entries_from_the_platform_report():
    by_slug = {c.slug: c for c in load_companies(COMPANIES_YAML)}
    assert by_slug["target"].ats_config == {
        "host": "target.wd5.myworkdayjobs.com",
        "tenant": "target",
        "site": "targetcareers",
    }
    assert by_slug["citi"].ats == "eightfold"
    assert by_slug["nokia"].ats == "oracle_hcm"
    assert by_slug["bosch"].ats_config == {"company_id": "BoschGroup"}
    assert by_slug["cohesity"].enabled and by_slug["cohesity"].ats == "workday"
