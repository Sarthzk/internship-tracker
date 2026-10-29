# Operations runbook

For whoever looks after the tracker. Everything runs on GitHub; there is no server to log in to.

## How it runs

```
cron-job.org (every 10 min)  ->  GitHub Actions "scrape" workflow
    validate data -> fetch ~100 company career pages -> filter -> compare with last time
    -> Telegram alerts -> save data/*.json -> regenerate README.md, README-archive.md, STATUS.md
    -> commit only if something changed
```

- Backup trigger: GitHub's own cron (minutes 7, 22, 37, 52). It is unreliable on quiet repos, which
  is why the outside timer exists.
- Where to look: the repo's **Actions** tab (one `scrape` run about every 10 minutes, about a
  minute long) and [STATUS.md](../STATUS.md) (health of every company).

## What each Telegram message means

| Message | Meaning | What to do |
|---|---|---|
| 🆕 *Company: Role* | A new India tech internship appeared | Apply (link is the official page) |
| 🆕 *N new internships* | Several at once, combined | Same |
| 📋 *Now tracking N companies…* | New companies were added; their already-open roles are not re-announced | Nothing |
| ⚠️ *Company has failed N runs in a row* | That company's page failed 3 times running | Open STATUS.md; see "A company keeps failing" |
| ✅ *Company is working again* | It recovered | Nothing |
| ⚠️ *Possible site change…* | A company's listings were replaced all at once (ids changed); not sent as new | Check the company's career page; the README has the listings |
| 🚨 *run crashed* | The tracker itself failed. Sent once per outage | Open the failed run in Actions; see "The run crashed" |
| 🚨 *workflow failed before the tracker could finish* | Install, data check or commit step failed | Same |
| ✅ *running normally again* | First good run after a crash | Nothing |
| ⏰ *did not run for N h* | Runs stopped, then resumed | Check the cron-job.org timer |
| ☀️ *Daily report* | 09:00 IST health summary | Read the failing list, if any |

No message from the tracker for a long time is normal when no new internships appear. The daily
report is the proof it is alive: if it does not arrive at 09:00 IST, check Actions.

## Common tasks

### Pause or resume everything
- Pause: in cron-job.org disable the job, and in GitHub **Actions -> scrape -> ... -> Disable
  workflow** (stops the backup cron too).
- Resume: enable both again, then run the workflow once by hand.

### A company keeps failing
1. Open STATUS.md for the error text (for example `HTTP 429`, `unexpected shape`).
2. Run `uv run python -m tracker check --companies <slug>` locally, and the **cloud-check**
   workflow (Actions -> cloud-check -> Run workflow, input the slug) to see if GitHub's servers are
   blocked while your laptop is fine.
3. `HTTP 429`/`403` from GitHub only: do not work around the block. Disable the company (below) or
   switch to another host for the same data if the site offers one (see `public_host` in
   `data/companies.yaml`).
4. `unexpected shape`: the site changed its page or API. The fetcher fails loudly on purpose. Fix
   the fetcher in `tracker/fetchers/` and add a fixture test.

### Turn a company off or on
Set `enabled: false` (or `true`) in `data/companies.yaml` and commit. Its listings stay as they are.
Turn a company on only after the cloud-check passes for it.

### Add a company (3 steps)
1. Find its platform: open its careers page, DevTools -> Network -> Fetch/XHR while searching.
   Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Oracle HCM, Eightfold and Phenom need only a
   config line (see the header of `data/companies.yaml`).
2. Add it with `enabled: false`, push, run **cloud-check** with its slug.
3. If it is OK, set `enabled: true`. You get one "Now tracking" message.

### Roll back a bad data commit
`git revert <commit>` and push. Note: if alerts were already sent, listings that come back as "new"
can alert once more (rare, harmless).

### Rotate the Telegram bot token
Telegram -> @BotFather -> `/revoke` -> pick the bot -> copy the new token. Update the GitHub secret
`TELEGRAM_BOT_TOKEN` (Settings -> Secrets and variables -> Actions). Never paste the token in chat,
code or logs.

### Renew the timer token (yearly)
The cron-job.org job uses a fine-grained GitHub token with only **Actions: Read and write** on this
repo, set to expire. Create a new one before it does and update the `Authorization` header in the job
(docs/SETUP.md section 7).

### The run crashed
Open the failed run in Actions and read the red step. Typical causes: a data file edited by hand
(`uv run python -m tracker validate` says which), or a dependency problem. Fix, push, and the next run
recovers by itself (you get a ✅).

## Safety rules the tracker keeps
- Never closes a listing because a fetch failed or came back suspiciously empty (24 h grace).
- Only official public job pages and APIs; an honest User-Agent; one request at a time per site with
  a delay; retries only on network errors, 429 and 5xx; never works around a site's bot protection.
- Stores title, company, location and link only. No job descriptions.
- Secrets only in GitHub secrets; Telegram URLs (which contain the token) are never logged.
- A quiet run changes no files and makes no commit.
