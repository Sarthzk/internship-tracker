# Demo script (about 10 minutes)

Audience: the HOD. Goal: show that it works, that it is safe, and that it costs nothing.

## Before the meeting (5 minutes)
- [ ] Open [STATUS.md](../STATUS.md): the summary line should say `0 failing`.
- [ ] Open the repo's **Actions** tab: a green `scrape` run about every 10 minutes.
- [ ] Telegram open on your phone, chat with the bot visible.
- [ ] README open on desktop and on your phone (the tables scroll sideways on a phone).
- [ ] [PITCH.md](PITCH.md) printed or open, numbers still right (companies, open internships).

## The walkthrough

1. **The problem (1 min).** Seats at big companies fill up in days; students find out late.
2. **The public page (2 min).** Open the README. Scroll the tables: company, role, location,
   official apply link, age. Point out the archive link and the disclaimer ("verify on the company
   site").
3. **Coverage and health (2 min).** Open STATUS.md: 100 companies, which platform each uses, last
   success date, open internships. Say: "if a company breaks, it shows here and I get a message."
4. **It runs by itself (1 min).** Actions tab: a run every 10 minutes, each about a minute. Open one
   run to show the steps (validate, fetch, alert, commit). Say: "no server, no cost."
5. **The alert (1 min).** Show the Telegram chat: a real internship alert with the official link;
   the 9 AM daily report; the "now tracking" message when companies were added.
6. **Safety, live (2 min).** Actions -> **scrape** -> **Run workflow** -> tick **Demo only: fail on
   purpose** -> Run. Within about a minute your phone shows `🚨 workflow failed...`. Then run it
   again without the tick, and the next message is `✅ running normally again`. Say: "it tells me
   when something is wrong, once, and when it is fixed."
7. **The ask (1 min).** One-semester pilot with a college Telegram channel and a faculty mentor
   (see PITCH.md).

## Questions to expect
- **Is this allowed?** It reads only public job pages and official public APIs, identifies itself
  honestly, waits between requests, and skips any site that blocks it. It stores no personal data
  and no job descriptions, only title, company, location and link.
- **What does it cost?** Nothing. GitHub's free automation, no server. The only recurring chore is
  renewing one narrowly scoped GitHub token (it can only start this one workflow) once a year (see OPERATIONS.md).
- **What if you graduate?** The runbook (OPERATIONS.md) explains every alert and common fix; two
  student maintainers and a faculty mentor keep it going.
- **What if a company changes its site?** The check fails loudly instead of showing wrong data; the
  status page and a Telegram message tell us which company, and the old listings stay untouched.
- **Is the data correct?** Links are the companies' own pages. A listing is closed only after three
  clean checks. Batch and duration are not shown yet (planned, only when stated in the posting).
- **Which companies are missing?** A few, such as Meta, whose career site cannot be read reliably.
  Students can suggest more once the community form exists.
- **Can it send to everyone?** Yes: the same bot can post to a college channel. That is held back
  until you approve.

## After the demo
Tell me what the HOD asked for; I will turn it into the next tasks.
