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
