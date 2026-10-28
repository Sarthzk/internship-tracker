# Custom / Workday portals

One section per company whose portal is Workday or fully custom, i.e. anything
`scripts/detect_ats.py` could not detect. Phase 4 builds one fetcher per entry here, so record
enough detail to write and test it without reopening the browser.

## How to find the endpoint

1. Open the company's careers page and search for "intern" with a location of India.
2. Open browser dev tools → **Network** → filter **Fetch/XHR**, then reload or change the search.
3. Find the request that returns the job list as JSON. Right-click → *Copy as cURL*.
4. Replay it in a terminal and confirm it works **without cookies or auth tokens**. If it needs a
   login, a CAPTCHA, or a short-lived token, mark the company as not feasible.
5. Check `robots.txt` and the site's terms of use. Do not build fetchers for portals that forbid
   automated access.

Workday URLs look like `https://{host}/wday/cxs/{tenant}/{site}/jobs`, e.g. careers page
`https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite` → host `nvidia.wd5.myworkdayjobs.com`,
tenant `nvidia`, site `NVIDIAExternalCareerSite`.

---

## Template (copy below this line)

### <Company name> (`<company-slug>`)

| Field | Value |
|---|---|
| Portal type | workday / custom (name of vendor if known) |
| Careers page | https://... |
| JSON endpoint | `GET`/`POST` https://... |
| Required headers | e.g. `Content-Type: application/json` (no cookies / auth) |
| Request body / query | ```{"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}``` |
| Pagination | e.g. `offset` + `limit`, stop when `offset >= total` |
| India / intern filters | facet IDs or query params that narrow results, if any |
| Job ID field | e.g. `bulletFields[0]` or `externalPath` |
| Title / location / date fields | JSON paths |
| Posting URL | how to build the official link from the response |
| Detail endpoint | URL for a single posting's description (for enrichment) |
| robots.txt / ToS notes | allowed? any rate limits stated? |
| Works from GitHub Actions? | unknown / yes / blocked (date checked) |
| `ats_config` for companies.yaml | e.g. `{host: ..., tenant: ..., site: ...}` |
| Last verified | YYYY-MM-DD |

Notes: anything unusual (anti-bot headers, regional sub-sites, etc.).

---

<!-- Add company sections below. -->

## Phase 4 findings (2026-10-28)

Resolved with existing fetchers (config only, cloud-checked, enabled): American Express (Oracle HCM,
`egug.fa.us2.oraclecloud.com` / `CX_1`; the careers domain redirects there), Oracle (Oracle HCM
`eeho.fa.us2.oraclecloud.com` / `CX_45001`), Texas Instruments (Oracle HCM `edbz.fa.us2.oraclecloud.com`
/ `CX`), Salesforce (Workday `salesforce.wd12` / `External_Career_Site`), Cisco (Workday `cisco.wd5` /
`Cisco_Careers`), ServiceNow (SmartRecruiters `ServiceNow`; the careers site itself sits behind a
Cloudflare challenge, which we do not touch).

Found, but needs a new fetcher (not built, waiting for keep/drop):

| Company | Platform | Public JSON? | Notes |
|---|---|---|---|
| AMD | iCIMS "Jibe" | yes: `GET careers.amd.com/api/jobs?keywords=intern&page=N&limit=100` | `location=` filter does not take "India"; filter on `country`/`full_location`. 106 intern jobs worldwide = 2 requests. Fields: `req_id`, `title`, `country`, `full_location`, `posted_date`, `canonical_url`. 0 India interns right now. |
| Rippling | own ATS `ats.rippling.com` | yes: `GET ats.rippling.com/api/v2/board/rippling/jobs?searchQuery=intern&page=0&pageSize=100` | `items[].locations[].countryCode`, `url`, `name`. 9 intern jobs worldwide. |
| Adobe, Snowflake | Phenom | `POST /widgets` (body not captured) | Only 2 companies, below the "3+" threshold for a Phenom fetcher. |
| Intuit, Barclays | Radancy TalentBrew | HTML fragments only | Needs HTML parsing; fragile. |
| Nutanix | Umbraco job board (`/en/jobs/`) | HTML only | Server-rendered; fragile. |

Not resolved: Walmart (`careers.walmart.com` is the US store site and ignores intern/India; the Global
Tech India board was not found; the guessed Workday tenant returns 422), Cohesity (403 to our
requests, not worked around), Arcesium (429 on the first request), Persistent Systems (custom Angular
app, no feed seen), and not yet looked at: D. E. Shaw, AlphaGrep, Quadeye, Flipkart, Zomato (Eternal),
PhonePe, Zepto, Postman, Zoho, Media.net, Juspay.
