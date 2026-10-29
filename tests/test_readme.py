from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from tracker import readme
from tracker.models import Enrichment, Listing
from tracker.readme import END, START, cell, link, render_archive, render_listings, replace_section
from tracker.storage import save_listings

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)  # 17:30 IST on 2026-10-29


def listing(n: int, **overrides) -> Listing:
    data = {
        "id": f"lever:acme:{n}",
        "company": "Acme",
        "company_slug": "acme",
        "title": f"Software Engineer Intern {n}",
        "category": "swe",
        "locations": ["Bengaluru"],
        "is_remote": False,
        "url": f"https://example.com/jobs/{n}",
        "source": "lever",
        "external_id": str(n),
        "date_posted": date(2026, 10, 26),
        "first_seen": NOW - timedelta(days=5),
        "last_seen": NOW.date(),
    }
    data.update(overrides)
    return Listing.model_validate(data)


def closed(n: int, days_ago: int, **overrides) -> Listing:
    return listing(n, status="closed", closed_at=NOW - timedelta(days=days_ago), **overrides)


# --- escaping ---


def test_cell_escapes_pipes_newlines_and_markdown():
    assert cell("a | b\nc") == "a \\| b c"
    assert cell("Intern_2027 <b>x</b> [y]") == "Intern\\_2027 &lt;b&gt;x&lt;/b&gt; \\[y\\]"
    assert cell("") == "—"


def test_link_encodes_characters_that_end_the_target():
    assert link("https://x.com/a b/(1)") == "[Apply](https://x.com/a%20b/%281%29)"


# --- open table ---


def test_summary_and_columns():
    text = render_listings([listing(1)], NOW)
    assert "**1 open internship** across 1 company · Last updated: 2026-10-29 (IST)" in text
    assert "| Company | Role | Location | Batch | Duration | Apply | Age |" in text
    assert (
        "| Acme | Software Engineer Intern 1 | Bengaluru | — | — | "
        "[Apply](https://example.com/jobs/1) | 3d |"
    ) in text


def test_only_categories_with_open_listings_and_closed_excluded():
    text = render_listings([listing(1), listing(2, category="quant"), closed(3, 1)], NOW)
    assert "### Software Engineering (1)" in text and "### Quant & Trading (1)" in text
    assert "Data & ML" not in text and "Intern 3" not in text


def test_sorted_newest_first_using_first_seen_when_date_posted_missing():
    old = listing(1, date_posted=date(2026, 10, 1))
    new = listing(2, date_posted=date(2026, 10, 28))
    unknown = listing(3, date_posted=None, first_seen=NOW - timedelta(days=2))
    text = render_listings([old, unknown, new], NOW)
    assert text.index("Intern 2") < text.index("Intern 3") < text.index("Intern 1")
    assert "| 2d |" in text  # Intern 3: age from first_seen


def test_age_is_never_negative():
    text = render_listings([listing(1, date_posted=date(2026, 12, 1))], NOW)
    assert "| 0d |" in text


def test_batch_and_duration_from_enrichment():
    enrichment = Enrichment(
        eligible_batches=[2027, 2028], duration_months=6, model="m", enriched_at=NOW
    )
    text = render_listings([listing(1, enrichment=enrichment)], NOW)
    assert "| 2027, 2028 | 6 mo |" in text


def test_locations_deduped_capped_and_remote_marked():
    li = listing(1, locations=["Pune", "Pune", "Delhi", "Noida", "Mumbai"], is_remote=True)
    text = render_listings([li], NOW)
    assert "| Pune; Delhi; Noida +1 more (Remote) |" in text


def test_hostile_text_cannot_break_the_table():
    li = listing(1, title="Evil | Intern\n| x |", company="A|B")
    text = render_listings([li], NOW)
    row = next(line for line in text.splitlines() if "Evil" in line)
    assert row.count("|") - row.count("\\|") == 8  # 7 columns, unescaped pipes only at edges


def test_no_open_listings_message():
    assert "No open internships right now" in render_listings([], NOW)


def test_output_is_deterministic():
    items = [listing(2), listing(1), closed(3, 2)]
    assert render_listings(items, NOW) == render_listings(list(reversed(items)), NOW)
    assert render_listings(items, NOW) == render_listings(items, NOW + timedelta(hours=3))


# --- archive ---


def test_archive_keeps_last_90_days_only_with_closed_date():
    text = render_archive([closed(1, 5), closed(2, 89), closed(3, 91), listing(4)], NOW)
    assert "Intern 1" in text and "Intern 2" in text
    assert "Intern 3" not in text and "Intern 4" not in text
    assert "| Posted | Closed |" in text
    assert "| 2026-10-26 | 2026-10-24 |" in text
    assert text.index("Intern 1") < text.index("Intern 2")  # most recently closed first


def test_archive_empty_message():
    assert "Nothing closed" in render_archive([], NOW)


# --- hand-written text is preserved ---


def test_replace_section_keeps_text_outside_markers():
    original = f"# Title\n\nintro\n\n{START}\nold\n{END}\n\n## Footer\n"
    updated = replace_section(original, "new\n")
    assert updated == f"# Title\n\nintro\n\n{START}\nnew\n{END}\n\n## Footer\n"
    assert replace_section(updated, "new\n") == updated  # idempotent


def test_replace_section_appends_markers_when_missing():
    updated = replace_section("# Title\n", "x\n")
    assert updated.startswith("# Title\n") and updated.count(START) == 1


# --- end to end ---


def test_generate_writes_files_and_second_run_changes_nothing(tmp_path: Path):
    data, root = tmp_path / "data", tmp_path
    save_listings(data / "listings.json", [listing(1), closed(2, 3)])
    (root / "README.md").write_text(f"# Hi\n\n{START}\n{END}\n\nbye\n", encoding="utf-8")
    assert readme.generate(data, root, NOW) is True
    text = (root / "README.md").read_text(encoding="utf-8")
    assert text.startswith("# Hi") and text.endswith("bye\n") and "Intern 1" in text
    assert "Intern 2" in (root / "README-archive.md").read_text(encoding="utf-8")
    assert readme.generate(data, root, NOW + timedelta(hours=2)) is False


# --- snapshot ---

SNAPSHOT = Path(__file__).parent / "fixtures" / "readme_snapshot.md"


def snapshot_listings() -> list[Listing]:
    return [
        listing(1, company="Google", title="Software Engineering Intern", locations=["Bengaluru"]),
        listing(
            2,
            company="Nvidia",
            title="ML Intern | Summer",
            category="data_ml",
            locations=["Pune", "Hyderabad"],
            date_posted=date(2026, 10, 28),
            enrichment=Enrichment(
                eligible_batches=[2027], duration_months=3, model="m", enriched_at=NOW
            ),
        ),
        listing(3, company="Quadeye", title="Quant Intern", category="quant", is_remote=True),
        closed(4, 10, company="Apple", title="Silicon Intern", category="hardware"),
    ]


def test_snapshot_of_open_tables():
    assert render_listings(snapshot_listings(), NOW) == SNAPSHOT.read_text(encoding="utf-8")


# --- status page ---


def company(slug: str, name: str, enabled: bool = True, tier: int = 1):
    from tracker.models import Company

    ats = "greenhouse" if enabled else "unknown"
    cfg = {"board_token": slug} if enabled else {}
    return Company(name=name, slug=slug, tier=tier, ats=ats, ats_config=cfg, enabled=enabled)


def test_status_page_orders_failing_first_and_counts_open_internships():
    from tracker.models import HealthRecord
    from tracker.readme import render_status

    companies = [
        company("zed", "Zed"),
        company("acme", "Acme"),
        company("fresh", "Fresh"),
        company("off", "Off", enabled=False),
        company("bad", "Bad|Co"),
    ]
    health = {
        "zed": HealthRecord(company_slug="zed", last_success=date(2026, 10, 29)),
        "acme": HealthRecord(company_slug="acme", last_success=date(2026, 10, 28)),
        "bad": HealthRecord(
            company_slug="bad",
            last_success=date(2026, 10, 27),
            consecutive_failures=3,
            last_error="FetchError: HTTP 429 from bad.example",
        ),
    }
    listings = [listing(1, company_slug="zed", id="lever:zed:1"), closed(2, 3)]
    text = render_status(companies, health, listings, NOW)
    assert (
        "**4 companies tracked** · 2 OK · 1 failing · 1 not tracked · Last updated: 2026-10-29"
        in text
    )
    rows = [line for line in text.splitlines() if line.startswith("| ") and "Company" not in line]
    names = [row.split(" | ")[0].removeprefix("| ") for row in rows]
    assert names == ["Bad\\|Co", "Acme", "Zed", "Fresh", "Off"]
    assert "⚠️ failing for 3 runs: FetchError: HTTP 429 from bad.example" in rows[0]
    assert "| Zed | greenhouse | ✅ OK | 2026-10-29 | 1 |" in rows[2]
    assert "⏳ waiting for the first run" in rows[3] and "⏸ not tracked" in rows[4]


def test_generate_writes_status_page_when_companies_exist(tmp_path: Path):
    data = tmp_path / "data"
    save_listings(data / "listings.json", [listing(1)])
    (data / "companies.yaml").write_text(
        "companies:\n  - {name: Acme, slug: acme, tier: 1, ats: greenhouse,"
        " ats_config: {board_token: acme}, enabled: true}\n",
        encoding="utf-8",
    )
    assert readme.generate(data, tmp_path, NOW) is True
    assert "| Acme | greenhouse |" in (tmp_path / "STATUS.md").read_text(encoding="utf-8")
    assert readme.generate(data, tmp_path, NOW + timedelta(hours=2)) is False
