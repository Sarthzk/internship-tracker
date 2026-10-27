# Setup: WhatsApp alerts and GitHub Actions

You do this once. It takes about 10 minutes.

## 1. Get your CallMeBot API key

CallMeBot is a free service that sends WhatsApp messages **to your own number only**. It is
unofficial, so it can be slow or stop working; that is why the tracker also tells you when a send
fails (it retries on the next run).

Follow the official steps on <https://www.callmebot.com/blog/free-api-whatsapp-messages/>. The
contact number and the exact sentence to send can change, so use what that page says. In short:

1. Save CallMeBot's WhatsApp number in your phone contacts.
2. From WhatsApp, send it the activation message shown on that page.
3. It replies with your **API key** (a short number). Keep it private.

Your phone number must include the country code, for example `+919876543210`.

## 2. Test it from your laptop (optional)

```bash
export CALLMEBOT_PHONE="+919876543210"
export CALLMEBOT_APIKEY="your-key"
uv run python -m tracker run
```

If this is the first run for a company you get one "Now tracking ..." message. Otherwise you get
one message per new internship. Never paste the key into a file in this repo.

## 3. Add the GitHub secrets

Repository → Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
|---|---|
| `CALLMEBOT_PHONE` | your number with country code, e.g. `+919876543210` |
| `CALLMEBOT_APIKEY` | the key CallMeBot sent you |

Without these the workflow still updates `data/`; it just skips WhatsApp (with a warning in the log).

## 4. Run the workflow once by hand

Actions tab → **scrape** → Run workflow. When it finishes:

- the log ends with `WhatsApp: N sent, M waiting`,
- you receive the messages on WhatsApp,
- a `chore(data): update listings` commit appears if anything changed,
- running it again right away sends nothing and commits nothing.

After that it runs on its own every 15 minutes. GitHub may start scheduled runs several minutes
late, so expect alerts within roughly 15 to 45 minutes of a posting appearing.

GitHub pauses scheduled workflows in a repository with no activity for 60 days. If alerts stop,
check the Actions tab and re-enable the workflow.

## 5. Checking a new company from GitHub's servers

Some career sites block cloud IPs. Before enabling a company, run Actions → **cloud-check** with
its slug (for example `nvidia,intel`). It prints posting counts and saves nothing. If it fails
there but works on your laptop, keep the company disabled and note it in `docs/CUSTOM_PORTALS.md`.

## What the messages mean

- `🆕 Company: Role` + location + link: a new internship.
- `🆕 N new internships`: five or more arrived at once, combined into one message.
- `📋 Now tracking ...`: a company was fetched for the first time; its already-open internships
  are summarised once instead of one message each.
- `⚠️ Company has failed 3 runs in a row`: its fetcher is broken; sent once.
- `✅ Company is working again`: sent once, after a `⚠️`.
- `🚨 internship-tracker run crashed`: the whole run failed (the Action also shows red).
