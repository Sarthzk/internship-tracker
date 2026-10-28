"""India location matching, internship detection, category classification.

All matching is whole-word and case-insensitive, so "India" never matches "Indiana" and
"intern" never matches "internal" or "international".
"""

from __future__ import annotations

import re

from tracker.models import Category, RawPosting


def _words(*phrases: str) -> re.Pattern[str]:
    # Not `\b`: an underscore counts as a word character there, and titles like
    # "Engineering Intern_2027_HW" must still match "intern".
    alternation = "|".join(sorted(phrases, key=len, reverse=True))
    return re.compile(rf"(?<![^\W_])(?:{alternation})(?![^\W_])", re.IGNORECASE)


INDIA = _words(
    "india",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "pune",
    "mumbai",
    "navi mumbai",
    "gurugram",
    "gurgaon",
    "noida",
    "delhi",
    "new delhi",
    "chennai",
    "kolkata",
    "ahmedabad",
    "kochi",
    "thiruvananthapuram",
    "jaipur",
    "indore",
    "chandigarh",
    "coimbatore",
    "mysuru",
    "mysore",
)

INTERNSHIP = _words(
    "intern",
    "interns",
    "internship",
    "internships",
    "summer analyst",
    "summer associate",
    "co-op",
    "apprentice",
    "apprenticeship",
    "industrial trainee",
)

SENIORITY = _words("senior", "staff", "principal", "lead", "manager", "director")

# Checked in this order; the first match wins. Anything tech-looking but unmatched is `other`.
CATEGORY_KEYWORDS: list[tuple[Category, re.Pattern[str]]] = [
    (
        Category.quant,
        re.compile(r"\b(?:quant\w*|trading|trader|algorithmic)\b", re.IGNORECASE),
    ),
    (
        Category.data_ml,
        _words(
            "data science",
            "data scientist",
            "data engineer",
            "data engineering",
            "data analyst",
            "data analytics",
            "analytics",
            "machine learning",
            "deep learning",
            "ml",
            "ai",
            "artificial intelligence",
            "nlp",
            "computer vision",
            "research scientist",
            "applied scientist",
        ),
    ),
    (
        Category.hardware,
        _words(
            "hardware",
            "vlsi",
            "asic",
            "fpga",
            "rtl",
            "embedded",
            "silicon",
            "chip",
            "analog",
            "circuit",
            "firmware",
            "physical design",
            "design verification",
            "electrical",
            "electronics",
            "semiconductor",
        ),
    ),
    (
        Category.product,
        _words(
            "product manager",
            "product management",
            "associate product manager",
            "apm",
            "product analyst",
            "product design",
            "product designer",
            "ux",
            "ui/ux",
        ),
    ),
    (
        Category.swe,
        _words(
            "software",
            "sde",
            "swe",
            "developer",
            "engineer",
            "engineering",
            "backend",
            "back-end",
            "frontend",
            "front-end",
            "full stack",
            "full-stack",
            "fullstack",
            "mobile",
            "android",
            "ios",
            "devops",
            "sre",
            "site reliability",
            "security",
            "cloud",
            "infrastructure",
            "platform",
            "qa",
            "sdet",
            "test automation",
            "programmer",
            "technology",
            "technical",
            "tech",
            "it",
        ),
    ),
]

NON_TECH = _words(
    "hr",
    "human resources",
    "people",
    "talent",
    "recruiting",
    "recruiter",
    "recruitment",
    "marketing",
    "brand",
    "content",
    "video",
    "editor",
    "copywriter",
    "copywriting",
    "social media",
    "graphic",
    "communications",
    "public relations",
    "legal",
    "patent",
    "counsel",
    "sales",
    "business development",
    "account manager",
    "customer success",
    "customer support",
    "finance",
    "accounting",
    "accountant",
    "audit",
    "tax",
    "treasury",
    "payroll",
    "procurement",
    "operations",
    "administrative",
    "office",
    "compliance",
)


def is_india_location(locations: list[str]) -> bool:
    return any(INDIA.search(loc) for loc in locations)


def is_internship(title: str) -> bool:
    return bool(INTERNSHIP.search(title)) and not SENIORITY.search(title)


def _tech_category(title: str) -> Category | None:
    for category, pattern in CATEGORY_KEYWORDS:
        if pattern.search(title):
            return category
    return None


def is_tech(title: str) -> bool:
    """Tech keywords win over non-tech ones ("Software Engineer Intern, Finance Systems" is tech).
    A title with neither (e.g. "Summer Analyst 2027") is kept as `other`."""
    return _tech_category(title) is not None or not NON_TECH.search(title)


def classify_category(title: str) -> Category:
    return _tech_category(title) or Category.other


def keep(posting: RawPosting) -> Category | None:
    """The category if this is an India tech internship, else None (drop it)."""
    if not is_internship(posting.title):
        return None
    if not is_india_location(posting.locations):
        return None
    if not is_tech(posting.title):
        return None
    return classify_category(posting.title)
