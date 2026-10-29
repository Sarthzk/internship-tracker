import pytest

from tracker.filters import (
    classify_category,
    is_india_location,
    is_internship,
    is_tech,
    keep,
)
from tracker.models import Category, RawPosting


@pytest.mark.parametrize(
    "locations,expected",
    [
        (["Bengaluru, Karnataka, India"], True),
        (["Remote - India"], True),
        (["Pune"], True),
        (["Navi Mumbai"], True),
        (["gurgaon"], True),
        (["Indianapolis, IN"], False),
        (["Indiana"], False),
        (["Indiana, USA", "London"], False),
        (["San Francisco", "Hyderabad"], True),
        ([], False),
    ],
)
def test_is_india_location(locations, expected):
    assert is_india_location(locations) is expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Software Engineer Intern", True),
        ("Interim Engineering Intern_2027_HW", True),
        ("Interim Engineer", False),
        ("Summer Analyst 2027", True),
        ("Engineering Internship - Summer 2027", True),
        ("SDE Co-op", True),
        ("Interns - Data", True),
        ("Internal Tools Engineer", False),
        ("International Sales Manager", False),
        ("Senior Intern Program Manager", False),
        ("Intern Lead", False),
        ("Software Engineer", False),
    ],
)
def test_is_internship(title, expected):
    assert is_internship(title) is expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Quantitative Research Intern", Category.quant),
        ("Trading Intern", Category.quant),
        ("Machine Learning Intern", Category.data_ml),
        ("Data Science Intern", Category.data_ml),
        ("VLSI Design Intern", Category.hardware),
        ("Product Management Intern", Category.product),
        ("Software Engineer Intern", Category.swe),
        ("Backend Developer Intern", Category.swe),
        ("Summer Analyst 2027", Category.other),
        ("Interim Engineering Intern_2027_HW", Category.hardware),
        ("Interim Engineering Intern_2027_SW", Category.swe),
        ("Research Sciences INTERN", Category.data_ml),
        ("Applied Sciences INTERN", Category.data_ml),
        ("2027 Intern - Research PhD Intern", Category.data_ml),
        ("Security Research INTERN", Category.swe),
    ],
)
def test_classify_category(title, expected):
    assert classify_category(title) is expected


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Software Engineer Intern", True),
        ("Summer Analyst 2027", True),
        ("Software Engineer Intern, Finance Systems", True),
        ("Marketing Intern", False),
        ("HR Intern", False),
        ("Legal Intern", False),
        ("Sales Development Intern", False),
        ("Finance Operations Intern", False),
        ("Video Editor Intern", False),
        ("Financial Analyst Intern", False),
        ("Interim Patent Intern", False),
        ("Intern, Company Secretary", False),
        ("Talent Acquisition Intern - IT Recruitment", False),
        ("HR Recruiter Intern, Engineering", False),
        ("Social Media Intern", False),
    ],
)
def test_is_tech(title, expected):
    assert is_tech(title) is expected


def posting(title: str, locations: list[str]) -> RawPosting:
    return RawPosting(
        company_slug="acme",
        source="lever",
        external_id="1",
        title=title,
        locations=locations,
        url="https://example.com/1",
    )


def test_keep_requires_all_three():
    assert keep(posting("Software Engineer Intern", ["Bengaluru"])) is Category.swe
    assert keep(posting("Software Engineer Intern", ["Indianapolis, IN"])) is None
    assert keep(posting("Software Engineer", ["Bengaluru"])) is None
    assert keep(posting("Marketing Intern", ["Bengaluru"])) is None
