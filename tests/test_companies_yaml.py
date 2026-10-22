from pathlib import Path

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


def test_custom_and_skipped_companies():
    by_slug = {c.slug: c for c in load_companies(COMPANIES_YAML)}
    for slug in ("amazon", "atlassian", "goldman-sachs"):
        assert by_slug[slug].ats == "custom" and not by_slug[slug].enabled
        assert "docs/VERIFIED_ENDPOINTS.md section C" in by_slug[slug].notes
    for slug in ("google", "apple"):
        assert by_slug[slug].tier == 2 and not by_slug[slug].enabled and by_slug[slug].notes


def test_only_companies_with_a_built_fetcher_type_are_enabled():
    # Phase 1 builds greenhouse / lever / ashby; everything else stays disabled until Phase 4.
    for c in load_companies(COMPANIES_YAML):
        if c.enabled:
            assert c.ats in {"greenhouse", "lever", "ashby"}, c.slug


def test_unresolved_companies_are_the_section_e_list():
    unresolved = {c.name for c in load_companies(COMPANIES_YAML) if c.ats == "unknown"}
    assert len(unresolved) == 36
    assert {"Snowflake", "Zomato", "Uber", "Media.net", "Morgan Stanley", "PayPal"} <= unresolved
