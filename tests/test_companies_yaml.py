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
