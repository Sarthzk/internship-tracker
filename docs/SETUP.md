# Setup: Telegram alerts and GitHub Actions

You do this once. It takes about 10 minutes.

## 1. Create your Telegram bot

1. In Telegram, open a chat with **@BotFather** (check it has the blue verified tick).
2. Send `/newbot`, then choose a name and a username ending in `bot`.
3. BotFather replies with the **bot token** (looks like `123456789:AA...`). Keep it private.
4. Open your new bot's chat and press **Start** (send it any message). A bot cannot message you
   until you have done this.

## 2. Find your chat id

After sending your bot a message, open this in a browser (replace `<TOKEN>`; do not share the page):

`https://api.telegram.org/bot<TOKEN>/getUpdates`

Look for `"chat":{"id":123456789,...}`. That number is your **chat id**.

## 3. Test it from your laptop (optional)

```bash
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"
uv run python -m tracker run
```

If this is the first run for a company you get one "Now tracking ..." message. Otherwise you get
one message per new internship. Never paste the token into a file in this repo.

## 4. Add the GitHub secrets

Repository → Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token BotFather sent you |
| `TELEGRAM_CHAT_ID` | your chat id |

Without these the workflow still updates `data/`; it just skips Telegram (with a warning in the log).

## 5. Run the workflow once by hand

Actions tab → **scrape** → Run workflow. When it finishes:

- the log ends with `Telegram: N sent, M waiting`,
- you receive the messages on Telegram,
- a `chore(data): update listings` commit appears if anything changed,
- running it again right away sends nothing and commits nothing.

After that it runs on its own every 15 minutes. GitHub may start scheduled runs several minutes
late, so expect alerts within roughly 15 to 45 minutes of a posting appearing.

GitHub pauses scheduled workflows in a repository with no activity for 60 days. If alerts stop,
check the Actions tab and re-enable the workflow.

## 6. Checking a new company from GitHub's servers

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
