# VERIFIED_ENDPOINTS.md

Findings from manual browser inspection on 21 Oct 2026. These endpoints were seen working from a normal browser session. **They have NOT been tested from GitHub Actions IPs or with plain httpx**, so verify each one in Phase 0.5 / Phase 4 before relying on it. Treat everything here as data, not as guaranteed contracts. Sites change.

Save this file as `docs/VERIFIED_ENDPOINTS.md` in the repo. It is separate from `docs/CUSTOM_PORTALS.md` (the template Phase 0 created); merge the details into that file when each fetcher is built.

---

## A. Standard ATS (use existing fetchers)

| Company | ATS | Config | Notes |
|---|---|---|---|
| Razorpay | greenhouse | `board_token: razorpaysoftwareprivatelimited` | 26 jobs, 20 India. The detector missed it because the slug is not "razorpay". |
| CRED | lever | `site: cred` | 9 jobs, 8 India. Verified. |
| Nvidia | workday | `host: nvidia.wd5.myworkdayjobs.com`, `tenant: nvidia`, `site: NVIDIAExternalCareerSite` | Endpoint seen: `/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs` |

From the Phase 0 detection report (kept, not re-verified here): Rubrik, Databricks, Stripe, Twilio, Tower Research Capital, Graviton Research Capital, Groww, InMobi (all Greenhouse); Meesho (Lever); Swiggy, Freshworks (SmartRecruiters). Still to verify: Snowflake (Ashby), Zomato (Lever `eternal`: only 4 jobs, 0 India, may be a different company).

**Do not trust SmartRecruiters "weak hits" or HTTP 500 errors from the Phase 0 report.** SmartRecruiters returns an empty list or 500 for company names that don't exist, so those results say nothing about the company.

Greenhouse, Lever and Ashby were probed with common slugs and returned nothing for: PhonePe, Zepto, Postman, BrowserStack, Sprinklr, Juspay, ShareChat, Dream11, Flipkart, Rippling, Cohesity, Nutanix, Arcesium, AlphaGrep, Quadeye, Zoho, Media.net, D. E. Shaw, Uber, Intuit, ServiceNow, Cisco. They use another system or a different slug. Phase 0.5 finds out which.

---

## B. Shared platforms needing a NEW generic fetcher (one fetcher, many companies)

### B1. Eightfold (PCSX) — covers Microsoft, probably PayPal, Amex, Qualcomm

- Microsoft: `GET https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query=intern&location=India&start=0&sort_by=timestamp`
- Response: `data.positions[]` with `id`, `name`, `locations[]`, `standardizedLocations`, `postedTs` (unix seconds), `department`, `workLocationOption`, `positionUrl` (relative, e.g. `/careers/job/1970393556917520`). `data.count` is the total. Paginate with `start`.
- Job page URL = `https://{host}{positionUrl}`.
- Observed 21 Oct 2026: 5 India intern roles at Microsoft.
- Config shape: `{host: "apply.careers.microsoft.com", domain: "microsoft.com"}`. For other companies the host is typically `{company}.eightfold.ai` and the domain is the company's primary domain. **Unverified** for PayPal (`paypal.eightfold.ai`), Amex (`aexp.eightfold.ai`), Qualcomm (`qualcomm.eightfold.ai`); Phase 0.5 should check.
- Note: `jobs.careers.microsoft.com` redirects to `apply.careers.microsoft.com`. Use the apply host.

### B2. Oracle HCM (Candidate Experience) — covers JPMorgan, probably Oracle

- JPMorgan: host `jpmc.fa.oraclecloud.com`, site `CX_1001`.
- `GET https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber=CX_1001,keyword=%22intern%22,limit=25,offset=0,sortBy=POSTING_DATES_DESC` with header `Accept: application/json`.
- Response: `items[0].TotalJobsCount` and `items[0].requisitionList[]` with `Id`, `Title`, `PostedDate`, `PrimaryLocation`, `PrimaryLocationCountry`, `JobFamily`, `StudyLevel`, `WorkDurationMonths`, `ShortDescriptionStr`, `secondaryLocations`.
- **The keyword filter did not narrow results** (3,614 total for "intern"), so the fetcher must page through everything and apply our own `is_internship` filter, or add a location facet. Check whether a country/location facet parameter works (e.g. via the site's facets in the same response) to keep it small.
- Public job URL pattern (verify): `https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/{Id}`.
- `StudyLevel`, `WorkDurationMonths` and `WorkDurationYears` are structured fields: use them for enrichment before calling the LLM.

### B3. Phenom People — Adobe (others unknown)

- Adobe: `POST https://careers.adobe.com/widgets` (many calls on page load). Request body not captured. Needs inspection in dev tools: look for the request whose payload contains `"ddoKey": "refineSearch"` and note the JSON shape.
- Only build this fetcher if Phase 0.5 finds 3+ companies on Phenom. Otherwise treat Adobe as a single custom fetcher or tier 2.

---

## C. Single-company custom fetchers (documented endpoints)

### C1. Amazon — easy
- `GET https://www.amazon.jobs/en/search.json?base_query=intern&loc_query=India&country=IND&result_limit=100&offset=0`
- Response: `hits` (total), `jobs[]` with `id_icims`, `title`, `normalized_location`, `location`, `job_path` (relative), `posted_date` (e.g. "August 11, 2026"), `job_category`, `job_schedule_type`, `is_intern`, `university_job`, `description`, `basic_qualifications`.
- Job URL = `https://www.amazon.jobs{job_path}`. Paginate with `offset`.
- Use the `is_intern` / `university_job` flags in addition to title keywords.

### C2. Atlassian — easy
- `GET https://www.atlassian.com/endpoint/careers/listings` returns one JSON array (about 2.4 MB, ~358 jobs, no pagination).
- Fields: `id`, `title`, `type`, `locations[]` (strings like "Bengaluru - India ..."), `category`, `overview`, `responsibilities`, `qualifications`, `applyUrl`, `portalJobPost.portalUrl`.
- Link users to the official Atlassian job page, not the raw iCIMS portal URL, if a public page URL can be derived; otherwise use `portalUrl`.
- Observed: 12 intern roles total, none in India right now.

### C3. Goldman Sachs — medium
- `POST https://api-higher.gs.com/gateway/api/v1/graphql`, `Content-Type: application/json`.
- Working query shape (validated by error messages; it returned valid but empty results):
  ```
  query GetRoles($searchQueryInput: RoleSearchQueryInput!) {
    roleSearch(searchQueryInput: $searchQueryInput) {
      totalCount
      items { roleId jobTitle locations { primary state country } division jobFunction corporateTitle externalSource { sourceId } }
    }
  }
  ```
  variables: `{"searchQueryInput": {"page": {"pageSize": 20, "pageNumber": 0}, "sort": {"sortStrategy": "RELEVANCE", "sortOrder": "DESC"}, "experiences": ["EARLY_CAREER"], "filters": [{"filterCategoryType": "LOCATION", "filters": [{"filter": "Bengaluru", "subFilters": []}]}], "searchTerm": "intern"}}`
- `experiences` is **required** (non-null list of enum `RoleSearchExperience`; `EARLY_CAREER` and `PROFESSIONAL` are accepted; other values unknown).
- Without filters, `EARLY_CAREER` returned 4 roles globally on 21 Oct 2026. With a Bengaluru/Hyderabad filter it returned 0. Intern programs may be seasonal, so also test a broader query (no `searchTerm`) to confirm the filters behave.
- Job URL is probably `https://higher.gs.com/roles/{roleId}` (**verify**).
- The GraphQL schema is undocumented and may change without notice. Make this fetcher fail loudly (admin alert) on schema errors.

---

## D. Hard / skip at launch (tier 2)

- **Google**: job data is embedded in the HTML of `https://www.google.com/about/careers/applications/jobs/results/?q=intern&location=India` inside `AF_initDataCallback` script blocks. Parsing that is fragile. Skip at launch; revisit later.
- **Apple**: `https://jobs.apple.com/en-in/search?search=intern&location=india-INDC`; no public JSON endpoint found in the page's requests. Skip at launch.

---

## E. Not yet resolved (Phase 0.5 will detect)

Morgan Stanley (the student programs page 404'd; try `/careers/career-opportunities-search`), Salesforce, Oracle, Intuit, ServiceNow, Qualcomm, Intel, AMD, Texas Instruments, Cisco, Walmart Global Tech, Uber, Visa, Mastercard, PayPal, American Express, Flipkart, PhonePe, Zepto, Postman, BrowserStack, Zoho, Sprinklr, Juspay, ShareChat, Dream11, Media.net, Zomato, D. E. Shaw, Arcesium, AlphaGrep, Quadeye, Nutanix, Cohesity, Rippling, Snowflake (verify).
