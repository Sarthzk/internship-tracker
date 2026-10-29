# India Tech Internships Tracker: a one-page proposal

*Prepared for the HOD. All figures are from the live system on 30 Oct 2026.*

## The problem
Good internships at companies like Google, Microsoft, Nvidia, Goldman Sachs and Quadeye are posted on
each company's own career page, often for only a few days, and many have limited seats. Students
find out late, by luck, or through scattered WhatsApp forwards, and miss deadlines they were
eligible for.

## What it does
It watches the official career pages of **100 companies** and detects new **tech internships located
in India** within about 10 to 15 minutes of being posted. Then it:

1. **Alerts** the owner on Telegram: company, role, location and a link to the official page.
2. **Publishes a public table** on the project's GitHub page, grouped by role type (software, data
   and ML, quant, hardware, product) and sorted by newest, with a separate archive of closed roles.
3. **Shows its own health** on a status page: which companies are checked, which are failing, and
   how many internships each currently has.

Right now it tracks **36 open India internships across 15 companies** (it is the off-season; most
summer-2027 programs open between November and January).

## Why it is trustworthy
- **Official sources only.** Links go to the company's own page, with a "verify on the company site"
  notice. We do not scrape social media, aggregators or private data.
- **Polite and above-board.** Public job pages and APIs only, an honest identifying User-Agent, one request
  at a time per site, with delays. If a site blocks us, we skip that company rather than work around it.
- **No personal data.** Nothing about students is collected or stored. Only job title, company,
  location and link are saved; job descriptions are never stored.
- **Careful about closing listings.** A listing is only marked closed after three clean checks, so a
  temporary website problem cannot make real openings disappear.
- **Self-monitoring.** It sends an alert if a company's page fails repeatedly, if the system stops
  running, or if a website suddenly changes its structure; and a daily 9 AM health report. In its first 11 hours
  with these checks it completed **68 of 68 runs without a failure**.
- **Tested.** About 470 automated tests that run without touching the internet.

## Cost and effort
- **Cost: Rs 0.** It runs on GitHub's free automation; there is no server, database or hosting bill.
- **Maintenance:** about 30 minutes a month for one volunteer (check the status page, fix a company
  whose career page changed). A runbook is written for handing it over.

## How the college could use it
1. **Pilot (now):** the tracker alerts one owner only, for the demo.
2. **Student channel:** with approval, the same bot posts new internships to a college Telegram
   channel (one setting, already designed).
3. **College home:** move the project under a college GitHub organization with two student
   maintainers and a faculty mentor, so it outlives any one batch.
4. **Placement-cell integration (optional):** the data file can feed a department page or newsletter.

## What it does not do (honest limits)
- It covers 100 companies, not every company. A few large employers (for example Meta) have career
  sites that cannot be read reliably, and some companies publish only through campus drives.
- It reports what companies publish. Eligibility (batch, CGPA, stipend) is not shown yet.
- Alerts are fast but not instant (about 10 to 15 minutes).

## Roadmap (each step only with approval)
- Show **graduation batch, duration and stipend** per internship, extracted only when the posting
  states them (AI-assisted, never guessed).
- **Public student channel** and a **community submission form** so students can report companies
  and closed listings.
- College-specific filters (branch, batch) and a simple website, if there is demand.

## The ask
Approval to (1) run a pilot with a college Telegram channel for one semester, and (2) list the project
as a student-run service of the department, with a faculty mentor.
