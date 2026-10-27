# Platform fingerprint report

Generated 2026-10-27 07:10 UTC by `scripts/fingerprint_platforms.py`. Suggestions only: companies.yaml is not modified.

36 companies covered. Verified = a live API call returned HTTP 200 and at least one job. Job counts are for the whole board; India counts are approximate (`≥` = counted from a sample).

## Summary

- Workday: 5 (5 verified, 0 unverified)
- Eightfold: 3 (3 verified, 0 unverified)
- Oracle HCM: 1 (1 verified, 0 unverified)
- Phenom: 2
- Lever: 1 (0 verified, 1 unverified)
- icims (unsupported): 1
- blocked: 2
- error: 1
- js-rendered: 4
- no-signal: 14
- not-found: 2

## Results

| Company | Platform | Config | Verified? | Jobs | India jobs | Notes |
|---|---|---|---|---|---|---|
| Uber | Oracle HCM | {host: iaziqy.fa.ocs.oraclecloud.com, site: UberCareers} | ✅ verified | 730 | ≥5 | India count is a sample: first 125 of 730 jobs, newest first; evidence: https://iaziqy.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/UberCareers/my-profile/sign |
| Salesforce | no-signal | — | — | — | — |  |
| Oracle | js-rendered | — | — | — | — |  |
| Intuit | no-signal | — | — | — | — |  |
| ServiceNow | no-signal | — | — | — | — |  |
| Qualcomm | Eightfold | {host: app.eightfold.ai, domain: qualcomm.com} | ✅ verified | 2077 | 573 | evidence: https://app.eightfold.ai/careers?domain=qualcomm.com |
| Intel | Workday | {host: intel.wd1.myworkdayjobs.com, tenant: intel, site: External} | ✅ verified | 793 | ≥14 | India count is approximate: 'N Locations' entries are not expanded; evidence: https://intel.wd1.myworkdayjobs.com/External/page/6042070b79e01001f04fa9b468070000 |
| AMD | icims (unsupported) | {host: internal-amd.icims.com} | — (detected only) | — | — | evidence: https://internal-amd.icims.com/jobs/search?back=none&redirect=search |
| Texas Instruments | js-rendered | — | — | — | — |  |
| Cisco | Phenom | {host: careers.cisco.com} | — (detected only) | — | — | evidence: text mention of phenompeople |
| Walmart Global Tech | no-signal | — | — | — | — |  |
| Nutanix | no-signal | — | — | — | — |  |
| Cohesity | blocked | — | — | — | — | HTTP 403 |
| Snowflake | Phenom | {host: careers.snowflake.com} | — (detected only) | — | — | evidence: text mention of phenompeople |
| Rippling | no-signal | — | — | — | — |  |
| PayPal | Eightfold | {host: paypal.eightfold.ai, domain: paypal.com} | ✅ verified | 320 | 14 | evidence: https://paypal.eightfold.ai/careers |
| Visa | Workday | {host: visa.wd5.myworkdayjobs.com, tenant: visa, site: Visa} | ✅ verified | 843 | ≥12 | India count is approximate: 'N Locations' entries are not expanded; evidence: https://visa.wd5.myworkdayjobs.com/Visa |
| Mastercard | Workday | {host: mastercard.wd1.myworkdayjobs.com, tenant: mastercard, site: CorporateCareers} | ✅ verified | 1151 | ≥30 | India count is approximate: 'N Locations' entries are not expanded; also seen: phenom; evidence: https://mastercard.wd1.myworkdayjobs.com/CorporateCareers |
| American Express | not-found | — | — | — | — | HTTP 404 |
| Morgan Stanley | Eightfold | {host: morganstanley.eightfold.ai, domain: morganstanley.com} | ✅ verified | 1247 | 96 | evidence: https://morganstanley.eightfold.ai/careers |
| D. E. Shaw | no-signal | — | — | — | — |  |
| Arcesium | blocked | — | — | — | — | HTTP 429 |
| AlphaGrep | not-found | — | — | — | — | HTTP 404 |
| Quadeye | no-signal | — | — | — | — |  |
| Flipkart | error | — | — | — | — | ConnectTimeout:  |
| Zomato | js-rendered | — | — | — | — |  |
| PhonePe | no-signal | — | — | — | — |  |
| Zepto | js-rendered | — | — | — | — |  |
| Postman | no-signal | — | — | — | — |  |
| BrowserStack | Workday | {host: browserstack.wd3.myworkdayjobs.com, tenant: browserstack, site: External} | ✅ verified | 30 | 27 | India count is approximate: 'N Locations' entries are not expanded; evidence: https://browserstack.wd3.myworkdayjobs.com/External |
| Zoho | no-signal | — | — | — | — |  |
| Sprinklr | Workday | {host: sprinklr.wd1.myworkdayjobs.com, tenant: sprinklr, site: careers} | ✅ verified | 76 | 12 | India count is approximate: 'N Locations' entries are not expanded; evidence: https://sprinklr.wd1.myworkdayjobs.com/careers?_gl=1*zwwtok*_ga*MjE0MDMwOTMyMC4xNzExMjkwMTcz*_ga_GD4 |
| Media.net | no-signal | — | — | — | — |  |
| Juspay | no-signal | — | — | — | — |  |
| ShareChat | no-signal | — | — | — | — |  |
| Dream11 | Lever | {site: dreamsports} | ⚠️ unverified guess | — | — | lever: HTTP 404 from lever board 'dreamsports'; evidence: https://jobs.lever.co/dreamsports |

## Suggested companies.yaml updates (verified only)

- Uber (`uber`): `ats: oracle_hcm, ats_config: {host: iaziqy.fa.ocs.oraclecloud.com, site: UberCareers}`
- Qualcomm (`qualcomm`): `ats: eightfold, ats_config: {host: app.eightfold.ai, domain: qualcomm.com}`
- Intel (`intel`): `ats: workday, ats_config: {host: intel.wd1.myworkdayjobs.com, tenant: intel, site: External}`
- PayPal (`paypal`): `ats: eightfold, ats_config: {host: paypal.eightfold.ai, domain: paypal.com}`
- Visa (`visa`): `ats: workday, ats_config: {host: visa.wd5.myworkdayjobs.com, tenant: visa, site: Visa}`
- Mastercard (`mastercard`): `ats: workday, ats_config: {host: mastercard.wd1.myworkdayjobs.com, tenant: mastercard, site: CorporateCareers}`
- Morgan Stanley (`morgan-stanley`): `ats: eightfold, ats_config: {host: morganstanley.eightfold.ai, domain: morganstanley.com}`
- BrowserStack (`browserstack`): `ats: workday, ats_config: {host: browserstack.wd3.myworkdayjobs.com, tenant: browserstack, site: External}`
- Sprinklr (`sprinklr`): `ats: workday, ats_config: {host: sprinklr.wd1.myworkdayjobs.com, tenant: sprinklr, site: careers}`

## Suggested careers_url changes (redirects)

- Uber: `https://uber.com/global/en/careers` → `https://jobs.uber.com/en/`
- Salesforce: `https://careers.salesforce.com` → `https://www.salesforce.com/company/careers/?bc=HL`
- Oracle: `https://careers.oracle.com` → `https://careers.oracle.com/en/sites/jobsearch`
- Qualcomm: `https://careers.qualcomm.com` → `https://careers.qualcomm.com/careers`
- Intel: `https://jobs.intel.com` → `https://intel.wd1.myworkdayjobs.com/External/page/6042070b79e01001f04fa9b468070000`
- AMD: `https://careers.amd.com` → `https://careers.amd.com/careers-home/jobs`
- Texas Instruments: `https://careers.ti.com` → `https://careers.ti.com/en/sites/CX`
- Cisco: `https://jobs.cisco.com` → `https://careers.cisco.com/global/en`
- Walmart Global Tech: `https://careers.walmart.com` → `https://careers.walmart.com/us/en/home`
- Nutanix: `https://nutanix.com/company/careers` → `https://careers.nutanix.com/en/`
- Cohesity: `https://cohesity.com/company/careers` → `https://www.cohesity.com/company/careers`
- Snowflake: `https://careers.snowflake.com` → `https://careers.snowflake.com/us/en`
- Rippling: `https://rippling.com/careers` → `https://www.rippling.com/careers`
- Visa: `https://corporate.visa.com/en/jobs` → `https://visa.wd5.myworkdayjobs.com/Visa`
- Mastercard: `https://careers.mastercard.com` → `https://careers.mastercard.com/us/en/`
- Morgan Stanley: `https://morganstanley.com/careers/career-opportunities-search` → `https://www.morganstanley.com/careers/career-opportunities-search`
- D. E. Shaw: `https://deshaw.com/careers` → `https://www.deshaw.com/careers`
- Quadeye: `https://quadeye.com/careers` → `https://www.quadeye.com/jobs`
- Zomato: `https://eternal.com/careers` → `https://www.eternal.com/careers/`
- PhonePe: `https://phonepe.com/careers` → `https://www.phonepe.com/careers/`
- Postman: `https://postman.com/company/careers` → `https://www.postman.com/company/careers/`
- BrowserStack: `https://browserstack.com/careers` → `https://www.browserstack.com/careers`
- Zoho: `https://zoho.com/careers` → `https://www.zoho.com/careers/`
- Sprinklr: `https://sprinklr.com/careers` → `https://www.sprinklr.com/careers/`
- Media.net: `https://media.net/careers` → `https://careers.media.net/`
- Dream11: `https://dreamsports.group/careers` → `https://www.dreamsports.group/lifeatdreamsports`

## Needs a human look (js-rendered, blocked, unverified, unsupported...)

- Salesforce (`salesforce`): no-signal
- Oracle (`oracle`): js-rendered
- Intuit (`intuit`): no-signal
- ServiceNow (`servicenow`): no-signal
- AMD (`amd`): other:icims
- Texas Instruments (`texas-instruments`): js-rendered
- Cisco (`cisco`): phenom
- Walmart Global Tech (`walmart-global-tech`): no-signal
- Nutanix (`nutanix`): no-signal
- Cohesity (`cohesity`): blocked — HTTP 403
- Snowflake (`snowflake`): phenom
- Rippling (`rippling`): no-signal
- American Express (`american-express`): not-found — HTTP 404
- D. E. Shaw (`de-shaw`): no-signal
- Arcesium (`arcesium`): blocked — HTTP 429
- AlphaGrep (`alphagrep`): not-found — HTTP 404
- Quadeye (`quadeye`): no-signal
- Flipkart (`flipkart`): error — ConnectTimeout: 
- Zomato (`zomato`): js-rendered
- PhonePe (`phonepe`): no-signal
- Zepto (`zepto`): js-rendered
- Postman (`postman`): no-signal
- Zoho (`zoho`): no-signal
- Media.net (`media-net`): no-signal
- Juspay (`juspay`): no-signal
- ShareChat (`sharechat`): no-signal
- Dream11 (`dream11`): lever — lever: HTTP 404 from lever board 'dreamsports'
