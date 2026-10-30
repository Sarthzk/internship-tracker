# CLAUDE.md — internship-tracker

This file is read by Claude Code at the start of every session. It contains the permanent rules for this project. The phase-by-phase work lives in `TASKS.md`.

## What this project is

`internship-tracker` automatically monitors the career portals of ~50 companies that Indian students want to intern at, detects **new tech internship postings located in India (or remote-India)**, and publishes them in three places:

1. `data/listings.json`: the single source of truth (the "database").
2. Telegram alerts to the owner's phone via a Telegram bot (the main goal: know within ~15–45 minutes).
3. `README.md`: auto-generated tables that students browse on GitHub.

Everything runs on GitHub Actions: an outside timer triggers the workflow every 10 minutes (`workflow_dispatch`, see docs/SETUP.md section 7) because GitHub's own cron is unreliable and kept as a backup. **There is no server, no database, and no hosting.** Keep it that way unless TASKS.md explicitly says otherwise.

## Stack

- Python 3.12, managed with **uv** (`uv sync`, `uv run ...`)
- `httpx` (async) for HTTP, `pydantic` v2 for schemas, `pyyaml` for config
- `groq` SDK for LLM enrichment (model name from env var `GROQ_MODEL`)
- Telegram Bot API (`sendMessage`) called directly with `httpx` (no Telegram library)
- Dev: `pytest`, `pytest-asyncio`, `respx` (mocking httpx), `ruff` (lint + format)

Do not add new dependencies unless a task requires it. If you think one is needed, say why in your summary.

## Commands

```bash
uv sync                                   # install
uv run ruff check . && uv run ruff format --check .
uv run pytest                             # all tests, must never hit the network
uv run python -m tracker run              # one full pipeline run
uv run python -m tracker run --dry-run    # no Telegram, no LLM, no file writes; prints a summary
uv run python -m tracker readme           # regenerate README from listings.json only
```

## Architecture / data flow (one run)

```
companies.yaml → fetchers (per ATS type) → normalize to RawPosting
  → filters (India location + internship + tech category)
  → diff against listings.json (new / still open / missing)
  → enrich NEW listings via Groq (optional, capped per run; later phase)
  → notify Telegram for listings where notified == false
  → save listings.json + health.json
  → regenerate README.md + README-archive.md (later phase)
```

### Layout

```
data/companies.yaml        company registry (name, slug, ats, ats config, tier)
data/listings.json         all listings, open and closed
data/health.json           per-company fetcher health
tracker/models.py          Pydantic models: Company, RawPosting, Listing, Enrichment, HealthRecord
tracker/fetchers/          one module per ATS: greenhouse, lever, ashby, smartrecruiters, workday, eightfold, oracle_hcm (phenom only if 3+ companies are confirmed on it)
tracker/fetchers/custom/   one module per company with a custom portal
tracker/filters.py         India location matching, internship detection, category classification
tracker/diff.py            merge fetched postings into existing listings
tracker/enrich.py          Groq extraction of batch / duration / term / stipend
tracker/readme.py          README + archive generation
tracker/notify.py          Telegram alerts: new listings + admin/health alerts
tracker/health.py          fetcher health tracking and alert decisions
tracker/guards.py          run-level safety checks (id churn)
tracker/schedule.py        which companies are due this run (`check_every_minutes`, default 10)
tracker/validate.py        data checks before anything is sent or committed (`python -m tracker validate`)
tracker/main.py            orchestration + CLI (python -m tracker)
scripts/                   one-off helper scripts (e.g. ATS detection)
tests/fixtures/            recorded JSON responses from each ATS
```

## Data model (keep in sync with tracker/models.py)

`Listing` fields:

| Field | Type | Notes |
|---|---|---|
| id | str | Stable: `"{source}:{company_slug}:{external_id}"`. Never changes. |
| company / company_slug | str | From companies.yaml |
| title | str | As posted |
| category | enum | `swe`, `data_ml`, `quant`, `hardware`, `product`, `other` |
| locations | list[str] | As posted |
| is_remote | bool | |
| url | str | Official posting / apply URL. Always link to the official page. |
| source | str | ATS type, `custom`, or `community` |
| external_id | str | ID from the ATS |
| date_posted | date or null | From ATS if available |
| first_seen | datetime (UTC, ISO 8601) | |
| last_seen | date (UTC day) | A date, not a datetime, so quiet runs don't change the file |
| status | enum | `open`, `closed` |
| missed_runs | int | Consecutive successful runs where it was absent |
| closed_at | datetime or null | |
| notified | bool | Set true only after the Telegram send succeeds |
| enrichment | Enrichment or null | See below |

`Enrichment` fields: `eligible_batches` (list of graduation years, e.g. `[2027, 2028]`, or null), `term` (`summer`, `winter`, `six_month`, `other`, `unknown`), `duration_months` (int or null), `stipend` (str or null, only if explicitly stated), `degree` (str or null), `model`, `enriched_at`.

`HealthRecord` fields (`health.json`): `company_slug`, `last_success` (date), `consecutive_failures`, `last_error`, `last_count` (reference level of postings: set at the first successful fetch and moved only when the count leaves a band of 20% or 5 postings around it, or switches between zero and non-zero, so normal drift leaves the file identical), `zero_since` (UTC datetime when a suspiciously low result, zero or a sharp drop, first appeared), `failure_alerted` (owner already told it's failing; cleared on recovery). No per-run timestamps.

`listings.json` and `health.json` are written with sorted keys, 2-space indent, and listings sorted by `id`, so git diffs stay small and readable. **A run where nothing real changed must leave both files byte-for-byte identical** (the workflow only commits real changes).

## Non-negotiable rules

1. **Never falsely close a listing.** A listing only increments `missed_runs` when its company's fetch **succeeded**. A fetch counts as failed if it raised an error, timed out (120 s per company), OR looked suspiciously low: zero postings, or postings that halved (and fell by at least 10) compared with the company's reference level `HealthRecord.last_count`. That suspicion only holds for 24 hours: if a company keeps returning the low result for 24 hours (tracked by `HealthRecord.zero_since`), it is accepted as real and counts as a success, so listings of a company that really shrank can close. Close only when `missed_runs >= CLOSE_AFTER_MISSES` (default 3). If a closed listing reappears, reopen it and reset `missed_runs`.
2. **Never store full job descriptions.** Descriptions may be fetched and passed to the LLM in memory, but only the extracted `Enrichment` fields are saved. We publish title, company, location, and a link to the official page, nothing more.
3. **Enrichment must not guess.** If the text does not state a batch, duration, or stipend, the field is null / `unknown`. The prompt and validation must enforce this.
4. **Be polite to career sites.** Identify with a User-Agent: `internship-tracker/<version> (+https://github.com/<owner>/internship-tracker)`. At most 1 concurrent request per host, a small delay between requests to the same host, 20s timeouts, retry with exponential backoff (max 3 attempts) only on network errors, 429, and 5xx. Where an API supports it, ask the server for India + "intern" results only instead of paging through every job.
5. **Tests never touch the network.** Use `respx` with fixtures in `tests/fixtures/`. Use fake Groq/Telegram clients in tests.
6. **Notifications are idempotent.** A listing is sent to Telegram once. Set `notified = true` only after Telegram returns `ok: true`; failed sends retry on the next run. The first time a company is fetched, its existing listings are marked notified and summarised in one message instead of one message each.
7. **Secrets come only from environment variables:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GROQ_API_KEY`, `GROQ_MODEL`. Never log or commit them. The Telegram Bot API takes the token in the URL path, so never log Telegram request URLs (log errors without the URL). If one is missing, that step is skipped with a warning, not a crash.
8. **One company failing must never crash the run.** Catch, record in health, continue.
   Related safety nets: bad data (`tracker/validate.py`) stops a run before it notifies or saves; a crash alerts only on the first failed run (and a ✅ follows recovery); listings replaced wholesale at one company (new ones appear while as many known ones vanish) are reported in one admin message instead of alerts; at most 10 Telegram messages per run; a daily 09:00 IST digest reports health.
9. **The README has a generated section** between `<!-- LISTINGS:START -->` and `<!-- LISTINGS:END -->`. Only `tracker/readme.py` writes inside it. Text outside the markers is hand-written and must be preserved.

## Filtering rules (summary; details live in tracker/filters.py)

- **India location:** match whole words/phrases (case-insensitive) against an alias list: India, Bengaluru/Bangalore, Hyderabad, Pune, Mumbai, Navi Mumbai, Gurugram/Gurgaon, Noida, Delhi/New Delhi, Chennai, Kolkata, Ahmedabad, Kochi, Thiruvananthapuram, Jaipur, Indore, Chandigarh, Coimbatore, Mysuru/Mysore, plus "Remote - India" style variants. Must NOT match "Indiana" or "Indianapolis".
- **Internship:** whole-word match for intern, interns, internship, summer analyst, summer associate, co-op, apprentice, industrial trainee. Must NOT match "internal" or "international". Exclude titles containing senior, staff, principal, lead, manager, director.
- **Category:** keyword classification into the enum, falling back to `other`. Non-tech postings (HR, marketing, legal, sales, finance-ops) are dropped, not stored.

## Code conventions

- Type hints everywhere; small pure functions where possible (filters, diff, readme are pure and easy to test).
- Fetchers implement one async interface: `async def fetch(company: Company, client: httpx.AsyncClient) -> list[RawPosting]`. They only fetch and normalize. No filtering, no diffing.
- Use `logging`, not print (except the CLI summary).
- All datetimes are timezone-aware UTC.
- Ruff defaults with line length 100.

## How to work in a session

1. Read `TASKS.md` and find the current phase (the first one with unchecked tasks).
2. Work on **that phase only**. Do not start the next phase.
3. Plan first, then implement, then run lint + tests until green.
4. Check off completed tasks in `TASKS.md`.
5. Commit with a conventional message, e.g. `feat(fetchers): add lever fetcher`.
6. End with a short summary: what was built, what was tested, anything the human must do manually (secrets, approvals, manual checks).

If a task is ambiguous or a decision would change the data model or these rules, stop and ask instead of guessing.
