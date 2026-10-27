# TASKS.md — internship-tracker

Phase-by-phase build plan. Project rules live in `CLAUDE.md`, so read that first.

**Instructions for Claude Code:** work on one phase at a time (the first phase with unchecked tasks). Check off tasks as you finish them. A phase is done only when every acceptance criterion passes. Items marked 👤 are for the human; do not try to do them yourself, but list them in your end-of-session summary.

---

## Phase 0 — Scaffold + company registry

Goal: a clean Python project and a verified list of ~50 companies with their ATS details.

### Tasks
- [x] Initialize the project with uv: `pyproject.toml` (Python 3.12, package `tracker`), dependencies from CLAUDE.md, ruff config (line length 100), pytest config (asyncio mode auto).
- [x] Create the folder layout from CLAUDE.md with empty modules and `__init__.py` files.
- [x] `.gitignore` for Python, `.env`, `.venv`, caches.
- [x] `.env.example` listing every env var from CLAUDE.md with empty values.
- [x] `tracker/models.py`: Pydantic models `Company`, `RawPosting`, `Listing`, `Enrichment`, `HealthRecord`, exactly as in the CLAUDE.md data model. Add unit tests for validation (bad enum values rejected, datetimes must be timezone-aware).
- [x] `Company` model fields: `name`, `slug`, `tier` (1 = must-have, 2 = nice-to-have), `ats` (`greenhouse`, `lever`, `ashby`, `smartrecruiters`, `workday`, `eightfold`, `oracle_hcm`, `phenom`, `custom`, `unknown`), `ats_config` (dict: e.g. `board_token`, `site`, `company_id`, Workday `host` + `tenant` + `site`, Eightfold `host` + `domain`, Oracle HCM `host` + `site`), `enabled` (bool), `notes` (optional).
- [x] `data/companies.yaml` seeded with the candidate list below, all `ats: unknown`, `enabled: false`.
- [x] `scripts/detect_ats.py`: for each company with `ats: unknown`, try likely slugs (lowercased name, without spaces/punctuation, common variants) against:
  - Greenhouse: `GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
  - Lever: `GET https://api.lever.co/v0/postings/{slug}?mode=json`
  - Ashby: `GET https://api.ashbyhq.com/posting-api/job-board/{slug}`
  - SmartRecruiters: `GET https://api.smartrecruiters.com/v1/companies/{slug}/postings`

  It prints a report (company → detected ATS, slug, total job count, count of India-located jobs) and writes suggestions to `data/ats_detection_report.md`. It does **not** modify companies.yaml automatically. Workday and custom portals cannot be guessed. List those as "needs manual check" in the report.
- [x] `docs/CUSTOM_PORTALS.md`: a template for documenting a company whose portal is Workday or custom (careers URL, the JSON endpoint found via browser dev tools, request shape, pagination, terms-of-service notes).

### Candidate companies (trim to ~50 after detection)

- **Big tech / product:** Google, Microsoft, Amazon, Apple, Adobe, Atlassian, Uber, Salesforce, Oracle, Intuit, ServiceNow, Nvidia, Qualcomm, Intel, AMD, Texas Instruments, Cisco, Walmart Global Tech, Nutanix, Rubrik, Cohesity, Databricks, Snowflake, Stripe, Twilio, Rippling, PayPal, Visa, Mastercard, American Express
- **Finance / quant:** Goldman Sachs, JPMorgan Chase, Morgan Stanley, D. E. Shaw, Tower Research Capital, Graviton Research Capital, Arcesium, AlphaGrep, Quadeye, Barclays
- **Indian product companies:** Flipkart, Swiggy, Zomato, Razorpay, CRED, PhonePe, Meesho, Zepto, Groww, Postman, BrowserStack, Freshworks, Zoho, Sprinklr, Media.net, Juspay, InMobi, Persistent Systems

### 👤 Human tasks
- [x] 👤 Run `uv run python scripts/detect_ats.py` and review the report.
- [x] 👤 For Workday / custom companies, open the careers page with browser dev tools (Network tab, filter Fetch/XHR) and note the JSON endpoint in `docs/CUSTOM_PORTALS.md`. (Moved to Phase 4: Claude does this in the built-in browser.)
- [x] 👤 Pick the final ~50: fill in `ats` + `ats_config`, set `enabled: true`, set `tier`. Aim for **at most ~8 custom-portal companies** at launch; the rest should be standard ATS types. (2026-10-27: list reviewed; added Barclays and Persistent Systems, removed Dream11 and ShareChat; the rest is resolved in Phases 3–4.)
- [x] 👤 Create the GitHub repo `internship-tracker` (public) and push.

### Acceptance criteria
- `uv sync`, `uv run ruff check .`, and `uv run pytest` all pass.
- `detect_ats.py` runs end-to-end and produces the report.
- companies.yaml loads into `Company` models without errors.

---

## Phase 0.5 — Platform fingerprinting for unresolved companies

Goal: find out which hiring system each unresolved company uses, locally and with no manual browsing. Read `docs/VERIFIED_ENDPOINTS.md` first (it holds findings from manual inspection on 21 Oct 2026 and the list of companies still unresolved in section E).

### Tasks
- [x] Copy `VERIFIED_ENDPOINTS.md` into `docs/` if it is not there already.
- [x] Update `tracker/models.py`, `data/companies.yaml` loading, and the CLAUDE.md fetcher list so the `ats` enum includes `eightfold`, `oracle_hcm`, `phenom` (add tests).
- [x] Update `data/companies.yaml` with everything already verified in `docs/VERIFIED_ENDPOINTS.md` (sections A to C): set `ats`, `ats_config`, `tier`, and `enabled: false` for any company whose fetcher is not built yet. Set `ats: custom` for Amazon, Atlassian and Goldman Sachs with the notes pointing at section C. Mark Google and Apple `tier: 2`, `enabled: false`, with the reason in `notes`.
- [x] Fix the false positives from Phase 0: remove SmartRecruiters from the detection logic unless the response has at least one job AND the returned company name loosely matches the company. Re-run detection logic tests accordingly.
- [x] `scripts/fingerprint_platforms.py`: for each company with `ats: unknown` (or listed in section E of VERIFIED_ENDPOINTS.md), fetch its careers URL(s) with httpx (follow redirects, polite User-Agent, 20s timeout, 1 request at a time with a short delay) and search the HTML, redirect chain, and linked URLs for these signatures:
  - Workday: `myworkdayjobs.com` (extract `host`, `tenant`, `site` from the URL: `https://{tenant}.wd{N}.myworkdayjobs.com/{locale?}/{site}`)
  - Eightfold: `eightfold.ai`, `/api/pcsx/`, `pcsx` (extract host)
  - Oracle HCM: `oraclecloud.com/hcmUI/CandidateExperience` (extract host + `sites/{site}`)
  - Phenom: `phenompeople.com`, `cdn.phenompeople`
  - Greenhouse: `greenhouse.io/{slug}`, `job-boards.greenhouse.io/{slug}`, `boards.greenhouse.io/{slug}`; Lever: `jobs.lever.co/{slug}`; Ashby: `jobs.ashbyhq.com/{slug}`; SmartRecruiters: `jobs.smartrecruiters.com/{slug}`
  - Others to record but not support yet: iCIMS, Taleo, SuccessFactors, Avature, Jobvite, Workable, Zoho Recruit, Darwinbox, Keka, Freshteam, Recruitee, Breezy
  - If the static HTML shows nothing (JavaScript-rendered page), record `js-rendered` and do not guess.
- [x] Add a "careers URL" field to `Company` (`careers_url`, optional) and fill it for every company in companies.yaml (use the starting points in the table below; fix redirects found by the script).
- [x] For each hit on greenhouse / lever / ashby / eightfold / oracle_hcm / workday, **verify the guess with a live API call** (the same endpoints described in `docs/VERIFIED_ENDPOINTS.md` and Phase 0) and record job count + India count. Do not mark anything verified without a successful response containing at least one job.
- [x] Write `data/platform_report.md`: table of company → platform → config → verified? → India job count → notes; then a summary count per platform (e.g. "Workday: 9, Eightfold: 3, ..."). Do NOT modify companies.yaml automatically for unverified guesses; the report only suggests.
- [x] Tests for the signature extractors using small saved HTML fixtures (no network).

### Starting careers URLs

Salesforce `careers.salesforce.com`, Oracle `careers.oracle.com`, Intuit `jobs.intuit.com`, ServiceNow `careers.servicenow.com`, Qualcomm `careers.qualcomm.com`, Intel `jobs.intel.com`, AMD `careers.amd.com`, Texas Instruments `careers.ti.com`, Cisco `jobs.cisco.com`, Walmart Global Tech `careers.walmart.com`, Uber `uber.com/global/en/careers`, Visa `corporate.visa.com/en/jobs`, Mastercard `careers.mastercard.com`, PayPal `paypal.eightfold.ai/careers` (guess), American Express `aexp.eightfold.ai/careers` (guess), Morgan Stanley `morganstanley.com/careers/career-opportunities-search`, Flipkart `flipkartcareers.com`, PhonePe `phonepe.com/careers`, Zepto `zeptonow.com/careers`, Postman `postman.com/company/careers`, BrowserStack `browserstack.com/careers`, Zoho `zoho.com/careers`, Sprinklr `sprinklr.com/careers`, Juspay `juspay.io/careers`, ShareChat `sharechat.com/careers`, Dream11 `dreamsports.group/careers`, Media.net `media.net/careers`, Zomato `eternal.com/careers`, D. E. Shaw `deshaw.com/careers`, Arcesium `arcesium.com/careers`, AlphaGrep `alphagrep.com/careers`, Quadeye `quadeye.com/careers`, Nutanix `nutanix.com/company/careers`, Cohesity `cohesity.com/company/careers`, Rippling `rippling.com/careers`, Snowflake `careers.snowflake.com`.

These are best guesses. If one 404s, record it in the report; do not invent alternatives.

### 👤 Human tasks
- [x] 👤 Run `uv run python scripts/fingerprint_platforms.py` and share `data/platform_report.md`.
- [x] 👤 For anything marked `js-rendered` or `unknown`, we decide together whether to open the page in the browser or drop the company. (Decided 2026-10-27: Claude checks them in the built-in browser in Phase 4.)

### Acceptance criteria
- `uv run ruff check .` and `uv run pytest` pass with no network access.
- The report covers every company that was unresolved.
- No company is marked verified without a live response containing jobs.

---

## Phase 1 — Core pipeline (local)

Goal: `uv run python -m tracker run` produces a correct `data/listings.json` from the Greenhouse and Lever companies (Ashby too, if any get added).

### Tasks
- [x] Apply the 9 verified companies from `data/platform_report.md` to `companies.yaml` (`enabled: false` until their fetcher exists) and commit the report.
- [x] `tracker/http.py`: a shared `httpx.AsyncClient` factory with the User-Agent, 20s timeout, per-host concurrency limit of 1, small per-host delay, and retry with exponential backoff (max 3 attempts; network errors, 429, 5xx only). Tests: retries on 503, no retry on 404.
- [x] `tracker/fetchers/base.py`: the fetcher interface and a registry mapping `ats` → fetch function.
- [x] `tracker/fetchers/greenhouse.py`, `lever.py`, `ashby.py`: fetch all postings and normalize to `RawPosting` (external_id, title, locations, is_remote, url, date_posted if available, description text in memory only). Record one real response per ATS into `tests/fixtures/` (trimmed to a few postings) and test normalization against it.
- [x] `tracker/filters.py`: `is_india_location`, `is_internship`, `classify_category`, `is_tech`. Table-driven tests covering at least:
  - "Bengaluru, Karnataka, India" ✅, "Remote - India" ✅, "Indianapolis, IN" ❌, "Indiana" ❌, "Pune" ✅
  - "Software Engineer Intern" ✅, "Summer Analyst 2027" ✅, "Internal Tools Engineer" ❌, "International Sales Manager" ❌, "Senior Intern Program Manager" ❌
  - category samples for every enum value, and non-tech titles dropped
- [x] `tracker/storage.py`: load/save `listings.json` and `health.json` (deterministic formatting as in CLAUDE.md; missing file = empty). Test: saving unchanged data twice gives identical bytes.
- [x] `tracker/diff.py`: pure function `merge(existing, fetched_by_company, fetch_status_by_company, today) -> (listings, new_ids)` implementing rule 1 in CLAUDE.md exactly. Tests:
  - new posting gets added with status open, `notified=false`
  - existing posting updates `last_seen` (a date) and resets `missed_runs`
  - absent posting after a **successful** fetch increments `missed_runs`; closes at 3
  - absent posting after a **failed** fetch does not change
  - company returning 0 postings after previously returning >0 is treated as failed, until it has returned 0 for 24 hours (`zero_since`), after which the zero counts as a success
  - closed posting that reappears is reopened
- [x] `tracker/health.py`: update per-company `HealthRecord` (last_success date, consecutive_failures, last_error, last_count, zero_since). No per-run timestamps.
- [x] `tracker/main.py` + `tracker/__main__.py`: CLI with `run` and `--dry-run`. Load enabled companies, fetch all concurrently (one failure never crashes the run), filter, diff, save. Print a summary: companies OK / failed, new, closed, total open.

### Acceptance criteria
- All tests pass with no network access.
- A real local run against the enabled companies produces a listings.json where every entry is an India-located tech internship.
- Running twice in a row on the same day produces **no diff at all** in `data/`.

### 👤 Human check
- [ ] 👤 Open listings.json and spot-check 10 entries against the real career pages.

---

## Phase 2 — WhatsApp alerts + automation (first usable version)

Goal: you get a WhatsApp message within ~15–45 minutes of a new posting, with no laptop involved.

### Tasks
- [ ] `tracker/notify.py`: CallMeBot client over httpx (`GET https://api.callmebot.com/whatsapp.php?phone=…&text=…&apikey=…`).
  - one message per new listing: company, role, location, apply link
  - 5 or more new listings in one run → one combined message (split if too long)
  - a short pause between messages (CallMeBot is rate-limited)
  - set `notified=true` only for listings whose message succeeded; failures retry next run
  - **never log the request URL** (it contains the API key)
  - first fetch of a company (no previous health record): mark its listings `notified=true` and send one summary message ("Stripe: 4 open internships") instead of one per listing
  - missing `CALLMEBOT_PHONE` / `CALLMEBOT_APIKEY` → skip sending with a warning; listings stay `notified=false`
- [ ] Admin alerts (same WhatsApp number): when a company reaches 3 consecutive failures (once, not every run; add a flag to `HealthRecord`), when it recovers, and when the run itself crashes (send, then re-raise so the Action shows red).
- [ ] Wire notifications into the pipeline before the final save, so `notified` flags are persisted in the same commit.
- [ ] Tests with a fake WhatsApp transport: per-listing vs combined, partial failure retry, first-run summary, failure alert sent once, key never appears in logs.
- [ ] `.github/workflows/scrape.yml`:
  - triggers: `schedule` cron every 15 minutes, plus `workflow_dispatch`
  - `concurrency: { group: scrape, cancel-in-progress: false }`
  - `permissions: contents: write`
  - steps: checkout, install uv, `uv sync`, run pipeline, commit and push only if `data/` changed, with message `chore(data): update listings`; on push conflict, pull with rebase and retry once
  - secrets from repository secrets (missing secrets just skip those steps)
- [ ] `.github/workflows/cloud-check.yml` (`workflow_dispatch`, input: company slugs): runs the fetchers for those companies from GitHub's servers and prints posting counts, without saving anything. Used before enabling any new fetcher, because some career sites block cloud IPs.
- [ ] `.github/workflows/tests.yml`: ruff + pytest on push and pull request (ignore pushes that only touch `data/` and README files).
- [ ] `docs/SETUP.md`: how to get a CallMeBot key and add the two GitHub secrets.

### 👤 Human tasks
- [ ] 👤 Get your CallMeBot API key and add `CALLMEBOT_PHONE` + `CALLMEBOT_APIKEY` as repository secrets.
- [ ] 👤 Trigger the workflow manually from the Actions tab; confirm the WhatsApp message arrives.
- [ ] 👤 Watch scheduled runs for a day; note delays or failures.

### Acceptance criteria
- A run with new listings sends each one to WhatsApp exactly once.
- A second run with no changes sends nothing and makes no commit.
- Temporarily breaking one company's config triggers exactly one admin message after 3 runs.

**🚀 First usable version after this phase.**

---

## Phase 3 — Cover the big companies

Goal: ~35+ companies tracked. Build the shared fetchers that cover the most companies first. Each fetcher: fixture tests (no network), asks the server for India + intern results where possible, then passes the cloud check before its companies get `enabled: true`.

### Tasks
- [ ] `tracker/fetchers/workday.py` → Nvidia, Intel, Visa, Mastercard, BrowserStack, Sprinklr. POST to `https://{host}/wday/cxs/{tenant}/{site}/jobs` with JSON `{"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}`, paginate using `total`, build the posting URL from `externalPath`. Use an India location facet if the site exposes one. Fetch the detail endpoint only for postings that pass the filters (and only when enrichment is on).
- [ ] `tracker/fetchers/eightfold.py` → Microsoft, Qualcomm, PayPal, Morgan Stanley. `GET https://{host}/api/pcsx/search?domain={domain}&query=intern&location=India&start=N`, paginate with `start` (docs/VERIFIED_ENDPOINTS.md B1). Re-check Qualcomm's generic `app.eightfold.ai` host.
- [ ] `tracker/fetchers/oracle_hcm.py` → JPMorgan, Uber (+ Texas Instruments / Oracle if Phase 4 confirms). The keyword filter does not narrow results (B2): find a working location facet; if none, check these companies hourly instead of every 15 minutes.
- [ ] `tracker/fetchers/smartrecruiters.py` → Swiggy, Freshworks (re-verify both boards live first).
- [ ] Custom fetchers in `tracker/fetchers/custom/`, registered by company slug: `amazon.py` (C1), `atlassian.py` (C2), `goldman.py` (C3, fail loudly on GraphQL schema errors).
- [ ] `tracker/fetchers/phenom.py` → Adobe, Cisco, Snowflake: **only if** the browser check confirms all three are on Phenom. Otherwise Adobe becomes a custom fetcher or tier 2.
- [ ] Record any site that blocks GitHub's servers in `docs/CUSTOM_PORTALS.md` and keep it disabled rather than working around the block.

### Acceptance criteria
- Every enabled company fetches successfully from GitHub Actions.
- No fetcher pages through thousands of jobs every 15 minutes.

---

## Phase 4 — Find the missing companies

Goal: every still-unknown company is either covered or consciously dropped.

### Tasks
- [ ] For each `ats: unknown` company, open its careers page in the built-in browser (read-only), watch the network requests for the job-search API, and write the findings into `docs/CUSTOM_PORTALS.md` (endpoint, method, request shape, pagination, India filter, notes). Priority: tier 1 first. Includes Barclays and Persistent Systems, and confirming Cisco / Snowflake (Phenom?), Texas Instruments / Oracle (Oracle HCM?), and AMD (iCIMS).
- [ ] Companies on an already-supported platform: add the `ats_config`, cloud-check, enable.
- [ ] Others: a small custom fetcher each, **at most ~8 custom fetchers in total** (they break most often). The rest are dropped or parked as tier 2 with a note.

### 👤 Human tasks
- [ ] 👤 Review the findings and decide keep / drop per company.

### Acceptance criteria
- No company left as `unknown` without a note explaining why.

---

## Phase 5 — Public README page

Goal: a browsable table on GitHub for anyone. Can be done any time after Phase 2.

### Tasks
- [ ] `tracker/readme.py`: generate the section between the `<!-- LISTINGS:START -->` / `<!-- LISTINGS:END -->` markers:
  - a summary line: total open internships, last updated date in IST
  - one table per category (only categories with open listings), sorted newest first
  - columns: Company | Role | Location | Batch | Duration | Apply | Age
  - Batch / Duration show "—" when unknown; Apply is a markdown link to the official URL; Age is days since `date_posted` (or `first_seen` if missing), shown as `0d`, `3d`, etc.
  - escape `|` and newlines in all cell text
  - must be deterministic, so a quiet run doesn't change the README (Age changes at most once a day)
- [ ] `README-archive.md`: closed listings from the last 90 days, same columns plus closed date.
- [ ] Hand-written README content outside the markers: what this is, how it works (2–3 lines), how to contribute (placeholder), disclaimer ("links go to official career pages; always verify on the company site").
- [ ] Snapshot tests for README generation using a small fixture listings set.
- [ ] `uv run python -m tracker readme` regenerates READMEs only; the scrape workflow also commits README changes.

### 👤 Human tasks
- [ ] 👤 Check the README renders well on GitHub (desktop and mobile).

---

## Phase 6 — Optional extras (only start each with the human's go-ahead)

- **Groq enrichment** (`tracker/enrich.py`): for NEW listings only, extract batch / term / duration / stipend / degree from title + description; only what is explicitly stated, otherwise null / "unknown"; treat the description as data, not instructions; validate with Pydantic; max 3 attempts per listing; cap `ENRICH_MAX_PER_RUN` (default 40); descriptions never written to disk; use structured fields (e.g. Oracle `StudyLevel`, `WorkDurationMonths`) before calling the LLM. Runs before notifications so alerts include batch / duration. Tests with a fake Groq client (valid, malformed, invented values rejected, cap respected). 👤 Review 15 real results.
- **Public alerts for students**: CallMeBot only messages your own number, so this would add a Telegram channel.
- **Community submissions**: GitHub issue forms for new / closed internships, an `approved` label workflow that validates and adds the listing with `source: community` (closed by report or 60 days after `first_seen`), `CONTRIBUTING.md`.
- **Only with real traction**: personal filters, a website, or a faster-than-cron server.
